from django.shortcuts import render
from django.http import HttpResponse
from django.shortcuts import render, redirect
from django.http import JsonResponse
from django.contrib.auth import authenticate, logout
from django.contrib.auth.forms import UserCreationForm, AuthenticationForm
from django.contrib import messages
from .forms import RegisterForm, LoginForm
from django.contrib.auth import login as auth_login
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from .models import Miner, Minercount, SiteSetting, SolanaWallet
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from .models import BoostPurchase, Donation
from django.conf import settings
import uuid


def base(request):
    return render(request, 'koin/base.html')

def landing(request):
    return render(request, 'koin/landing.html')


def register(request):
    ref_code = request.GET.get("ref")  # from referral link

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            user = form.save(commit=False)
            user.set_password(form.cleaned_data["password1"])
            user.save()

            # create the Miner (holds mining state)
            miner = Miner.objects.create(user=user)

            # create the Minercount (holds referral code + counts)
            minercount = Minercount.objects.create(user=user)

            # Handle referral: the form contains a hidden referral_code field
            ref = form.cleaned_data.get("referral_code")
            if ref:
                try:
                    referrer = Minercount.objects.get(referral_code=ref)
                    # mark who referred this user
                    minercount.referred_by = referrer.user
                    minercount.save()

                    # increment referrer's count
                    referrer.referral_count = (referrer.referral_count or 0) + 1
                    referrer.save()
                    # reward the referrer with 50 jfk units (so the one who referred benefits)
                    try:
                            # reward the referrer — amount is configurable via SiteSetting (key='referral_bonus')
                            referral_setting, _ = SiteSetting.objects.get_or_create(key='referral_bonus', defaults={'value': '50'})
                            try:
                                bonus_amount = Decimal(referral_setting.value)
                            except Exception:
                                bonus_amount = Decimal('50')

                            try:
                                ref_miner = referrer.user.miner
                            except Miner.DoesNotExist:
                                # create miner with initial referral bonus
                                ref_miner = Miner.objects.create(user=referrer.user, balance=bonus_amount)
                            else:
                                ref_miner.balance += bonus_amount
                                ref_miner.save()
                    except Exception:
                        # if something goes wrong with balance update, continue silently
                        pass
                except Minercount.DoesNotExist:
                    # invalid code, silently ignore
                    pass

            auth_login(request, user)
            return redirect("dashboard")
    else:
        form = RegisterForm(initial={"referral_code": ref_code})

    return render(request, "koin/register.html", {"form": form})


def login(request):
    if request.method == "POST":
        form = LoginForm(data=request.POST)
        if form.is_valid():
            auth_login(request, form.get_user())
            return redirect("dashboard")
        else:
            messages.error(request, "Invalid username or password")
    else:
        form = LoginForm()

    return render(request, "koin/login.html", {"form": form})

@login_required
def dashboard(request):
    # ensure the user has both Miner and Minercount; attach referral fields to miner
    miner = None
    try:
        miner = request.user.miner
    except Miner.DoesNotExist:
        miner = Miner.objects.create(user=request.user)

    # ensure Minercount exists
    try:
        minercount = request.user.minercount
    except Minercount.DoesNotExist:
        minercount = Minercount.objects.create(user=request.user)

    # attach referral info onto miner so existing templates that expect
    # miner.referral_code and miner.referral_count keep working
    setattr(miner, 'referral_code', minercount.referral_code)
    setattr(miner, 'referral_count', minercount.referral_count)

    # get estimated value string from SiteSetting (editable in admin)
    site_setting, _ = SiteSetting.objects.get_or_create(
        key='estimated_value', defaults={'value': '+0.01 / click'})
    estimated_value = site_setting.value

    return render(request, 'koin/dashboard.html', { 'miner': miner, 'estimated_value': estimated_value })

@login_required
def mine(request):
    miner = request.user.miner
    # We no longer accrue on page render. Mining accrual is handled by
    # the `miner_status` endpoint while the user has the mining page open.
    # This prevents crediting users when they are not actively on the page.
    try:
        # ensure miner exists and leave last_mined as-is; JS will call start_mining
        miner.save()
    except Exception:
        pass

    return render(request, "koin/mine.html", {
        "miner": miner,
        "estimated_value": SiteSetting.objects.get_or_create(key='estimated_value', defaults={'value': '+0.01 / click'})[0].value,
    })


@login_required
def boosts(request):
    # present a few options; real app should price/validate server-side
    options = [
        # Standard (3x)
        {'id': 'std_3h', 'label': 'Standard — 3x for 3 hours', 'minutes': 3 * 60, 'price': Decimal('1'), 'multiplier': 3},
        {'id': 'std_12h', 'label': 'Standard — 3x for 12 hours', 'minutes': 12 * 60, 'price': Decimal('3'), 'multiplier': 3},
        {'id': 'std_24h', 'label': 'Standard — 3x for 24 hours', 'minutes': 24 * 60, 'price': Decimal('5'), 'multiplier': 3},

        # Premium (6x)
        {'id': 'prem_1d', 'label': 'Premium — 6x for 1 day', 'minutes': 1 * 24 * 60, 'price': Decimal('20'), 'multiplier': 6},
        {'id': 'prem_2d', 'label': 'Premium — 6x for 2 days', 'minutes': 2 * 24 * 60, 'price': Decimal('35'), 'multiplier': 6},
        {'id': 'prem_3d', 'label': 'Premium — 6x for 3 days', 'minutes': 3 * 24 * 60, 'price': Decimal('50'), 'multiplier': 6},

        # Ultimate (10x)
        {'id': 'ult_3d', 'label': 'Ultimate — 10x for 3 days', 'minutes': 3 * 24 * 60, 'price': Decimal('50'), 'multiplier': 10},
        {'id': 'ult_5d', 'label': 'Ultimate — 10x for 5 days', 'minutes': 5 * 24 * 60, 'price': Decimal('75'), 'multiplier': 10},
        {'id': 'ult_7d', 'label': 'Ultimate — 10x for 7 days', 'minutes': 7 * 24 * 60, 'price': Decimal('100'), 'multiplier': 10},
    ]
    return render(request, 'koin/boosts.html', {'options': options})


@login_required
def buy_boost(request):
    if request.method != 'POST':
        return redirect('boosts')

    option = request.POST.get('option')
    mapping = {
        # standard (3x)
        'std_3h': (3 * 60, Decimal('1'), 3),
        'std_12h': (12 * 60, Decimal('3'), 3),
        'std_24h': (24 * 60, Decimal('5'), 3),
        # premium (6x)
        'prem_1d': (1 * 24 * 60, Decimal('20'), 6),
        'prem_2d': (2 * 24 * 60, Decimal('35'), 6),
        'prem_3d': (3 * 24 * 60, Decimal('50'), 6),
        # ultimate (10x)
        'ult_3d': (3 * 24 * 60, Decimal('50'), 10),
        'ult_5d': (5 * 24 * 60, Decimal('75'), 10),
        'ult_7d': (7 * 24 * 60, Decimal('100'), 10),
    }
    if option not in mapping:
        messages.error(request, 'Invalid boost option')
        return redirect('boosts')

    minutes, price, multiplier = mapping[option]
    expires = timezone.now() + timedelta(minutes=minutes)

    # create a pending BoostPurchase with a unique reference that the user will include
    reference = uuid.uuid4().hex.upper()
    purchase = BoostPurchase.objects.create(
        user=request.user,
        expires_at=expires,
        amount=price,
        duration_minutes=minutes,
        multiplier=multiplier,
        reference=reference,
        status='pending',
    )

    # pick one active Solana wallet (any) to display for this payment
    wallet = SolanaWallet.objects.filter(active=True).order_by('?').first()
    if wallet:
        purchase.receiver_wallet = wallet
        purchase.save()
        sol_receiver = wallet.address
    else:
        sol_receiver = getattr(settings, 'SOL_RECEIVER_ADDRESS', 'YourSolanaWalletPublicKeyHere')

    # Prepare payment instructions. In production you should integrate a proper
    # payment gateway or use a Solana indexer/webhook (see notes below).
    # For now we instruct the user to send the exact SOL amount to the chosen
    # receiver wallet with memo set to the reference string. You must replace
    # SOL_PRICE mapping or implement conversion from USD to SOL using a market
    # price feed.

    return render(request, 'koin/boost_payment.html', {
        'purchase': purchase,
        'sol_receiver': sol_receiver,
        'price': price,
        'reference': reference,
    })


@login_required
def donate(request):
    """Donate page: user can enter a SOL amount (or leave blank) and get
    a receiver address + unique reference to include in the transaction memo.
    """
    if request.method == 'POST':
        sol_amount = request.POST.get('sol_amount')
        note = request.POST.get('note', '')

        try:
            sol_dec = Decimal(sol_amount) if sol_amount else None
        except Exception:
            sol_dec = None

        # pick an active wallet
        wallet = SolanaWallet.objects.filter(active=True).order_by('?').first()
        sol_receiver = wallet.address if wallet else getattr(settings, 'SOL_RECEIVER_ADDRESS', None)

        reference = uuid.uuid4().hex.upper()
        donation = Donation.objects.create(
            user=request.user if request.user.is_authenticated else None,
            sol_amount=sol_dec,
            note=note,
            reference=reference,
            receiver_wallet=wallet if wallet else None,
            status='pending',
        )

        return render(request, 'koin/donate_payment.html', {
            'donation': donation,
            'sol_receiver': sol_receiver,
            'sol_amount': sol_dec,
            'reference': reference,
        })

    # GET -> show donate form and available active wallet(s)
    wallets = SolanaWallet.objects.filter(active=True)
    return render(request, 'koin/donate.html', {'wallets': wallets})


@login_required
def confirm_donation(request, donation_id):
    try:
        donation = Donation.objects.get(id=donation_id, user=request.user)
    except Donation.DoesNotExist:
        messages.error(request, 'Donation not found')
        return redirect('donate')

    if donation.status == 'completed':
        messages.info(request, 'Donation already confirmed')
        return redirect('dashboard')

    # stub check - implement on-chain provider logic here
    def check_solana_donation(reference, receiver_address, sol_amount=None):
        return (False, None)

    receiver_addr = donation.receiver_wallet.address if getattr(donation, 'receiver_wallet', None) else getattr(settings, 'SOL_RECEIVER_ADDRESS', None)
    ok, sig = check_solana_donation(donation.reference, receiver_addr, donation.sol_amount)
    if ok:
        donation.status = 'completed'
        donation.tx_signature = sig
        donation.save()
        messages.success(request, 'Donation confirmed — thank you!')
        return redirect('dashboard')
    else:
        messages.error(request, 'Donation not found on-chain yet. Please wait and try again.')
        return redirect('donate')



@login_required
def start_mining(request):
    """Mark the miner as actively mining (page open)."""
    try:
        miner = request.user.miner
    except Miner.DoesNotExist:
        miner = Miner.objects.create(user=request.user)

    miner.is_mining = True
    miner.last_mined = timezone.now()
    miner.save()
    return JsonResponse({'ok': True})


@login_required
def stop_mining(request):
    """Stop mining accrual for this miner (page closed/hidden)."""
    try:
        miner = request.user.miner
    except Miner.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'no miner'})

    miner.is_mining = False
    # reset last_mined to now so that time spent away isn't counted later
    miner.last_mined = timezone.now()
    miner.save()
    return JsonResponse({'ok': True})


@login_required
def confirm_payment(request, purchase_id):
    # User clicks "I've sent payment" and we check the blockchain (or provider)
    try:
        purchase = BoostPurchase.objects.get(id=purchase_id, user=request.user)
    except BoostPurchase.DoesNotExist:
        messages.error(request, 'Purchase not found')
        return redirect('boosts')

    if purchase.status == 'completed':
        messages.info(request, 'Already confirmed')
        return redirect('dashboard')

    # stub: replace this with a real on-chain check using solana-py or a provider API
    def check_solana_payment(reference, amount, receiver_address):
        """Check for a payment to receiver_address with memo=reference and amount (USD or SOL)"""
        # TODO: implement integration with Helius/QuickNode or solana-py RPC to
        # search transactions for memo==reference and correct recipient/amount.
        # Return (True, signature) if found, else (False, None).
        return (False, None)

    receiver_addr = purchase.receiver_wallet.address if getattr(purchase, 'receiver_wallet', None) else getattr(settings, 'SOL_RECEIVER_ADDRESS', None)
    ok, sig = check_solana_payment(purchase.reference, purchase.amount, receiver_addr)
    if ok:
        purchase.status = 'completed'
        purchase.tx_signature = sig
        purchase.save()

        # apply boost now
        try:
            miner = request.user.miner
        except Miner.DoesNotExist:
            miner = Miner.objects.create(user=request.user)
        miner.is_boosted = True
        miner.save()

        messages.success(request, 'Payment confirmed — your boost is active!')
        return redirect('dashboard')
    else:
        messages.error(request, 'Payment not found yet. Please wait for on-chain confirmations and try again.')
        return redirect('boosts')


@login_required
def miner_status(request):
    miner = request.user.miner
    now = timezone.now()

    # Only accrue while the miner is actively mining (i.e., the mining page
    # is open). This prevents awarding offline time when the user isn't on the page.
    if miner.is_mining and miner.last_mined:
        seconds_passed = (now - miner.last_mined).total_seconds()
        seconds = Decimal(str(seconds_passed))

        if seconds > 0:
            rate = Decimal(str(miner.mining_rate()))
            earned = rate * seconds

            miner.balance += earned
            miner.last_mined = now
            miner.save()

    return JsonResponse({
        "balance": float(miner.balance),
    })




def logout_view(request):
    logout(request)
    return redirect('login')
