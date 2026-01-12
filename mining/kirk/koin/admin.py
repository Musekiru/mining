from django.contrib import admin, messages
from django import forms
from django.utils import timezone
from datetime import timedelta
from decimal import Decimal

from .models import Miner, Minercount, SiteSetting, BoostPurchase, SolanaWallet, MinerRateChange, Donation


@admin.register(Miner)
class MinerAdmin(admin.ModelAdmin):
    # Custom ModelForm to expose an editable "effective_rate" field in admin.
    class MinerAdminForm(forms.ModelForm):
        effective_rate = forms.DecimalField(
            required=False,
            label='effective rate (units/sec)',
            max_digits=20,
            decimal_places=12,
        )

        class Meta:
            model = Miner
            fields = '__all__'

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            inst = kwargs.get('instance')
            if inst and inst.pk:
                try:
                    ef = inst.mining_rate()
                except Exception:
                    ef = inst.custom_rate or Decimal('0')
                self.fields['effective_rate'].initial = Decimal(str(ef))

    form = MinerAdminForm
    list_display = (
        'user',
        'balance',
        'is_boosted',
        'custom_rate',
        'current_rate',
        'last_mined',
    )

    list_filter = (
        'is_boosted',
    )

    search_fields = (
        'user__username',
        'user__email',
    )

    readonly_fields = (
        'last_mined', 'current_rate',
    )

    fieldsets = (
        ("User Info", {
            "fields": ("user",)
        }),
        ("Mining Info", {
            # include effective_rate (form-only field) so admins can edit it directly
            "fields": ("balance", "is_boosted", "custom_rate", "effective_rate", "last_mined")
        }),
    )

    ordering = ('-balance',)

    def current_rate(self, obj):
        try:
            return obj.mining_rate()
        except Exception:
            return None
    current_rate.short_description = 'effective rate (units/sec)'

    def save_model(self, request, obj, form, change):
        """Override save to allow setting effective_rate and record audits.

        If admin provided effective_rate, compute custom_rate = effective_rate / multiplier
        where multiplier is derived from active completed BoostPurchase rows.
        Then save and log a MinerRateChange if the custom_rate changed.
        """
        old_rate = None
        if change and obj.pk:
            try:
                old_obj = Miner.objects.get(pk=obj.pk)
                old_rate = old_obj.custom_rate
            except Miner.DoesNotExist:
                old_rate = None

        # If admin provided effective_rate, compute and set custom_rate before saving
        try:
            eff = None
            if form and hasattr(form, 'cleaned_data'):
                eff = form.cleaned_data.get('effective_rate')
            if eff is not None:
                # determine current multiplier from active completed boost purchases
                multiplier = 1
                try:
                    now = timezone.now()
                    bp = BoostPurchase.objects.filter(
                        user=obj.user, status='completed', expires_at__gt=now
                    ).order_by('-multiplier').first()
                    if bp and getattr(bp, 'multiplier', None):
                        multiplier = bp.multiplier
                except Exception:
                    multiplier = 1

                try:
                    obj.custom_rate = (Decimal(str(eff)) / Decimal(str(multiplier)))
                except Exception:
                    # leave custom_rate unchanged on conversion error
                    pass
        except Exception:
            pass

        super().save_model(request, obj, form, change)

        # after save, log if the custom_rate changed
        try:
            new_rate = obj.custom_rate
            if old_rate != new_rate:
                MinerRateChange.objects.create(
                    miner=obj,
                    changed_by=request.user,
                    old_rate=old_rate,
                    new_rate=new_rate,
                    note='Manual change from admin' if request.user else ''
                )
        except Exception:
            # don't let logging errors block admin save
            pass


@admin.register(Minercount)
class MinercountAdmin(admin.ModelAdmin):
    list_display = (
        'user',
        'referral_code',
        'referred_by',
        'referral_count',
        'balance',
    )
    search_fields = (
        'user__username',
        'referral_code',
        'referred_by__username',
    )
    readonly_fields = ('referral_code',)
    ordering = ('-referral_count',)


@admin.register(SiteSetting)
class SiteSettingAdmin(admin.ModelAdmin):
    list_display = ('key', 'value')
    search_fields = ('key', 'value')
    readonly_fields = ()


@admin.register(BoostPurchase)
class BoostPurchaseAdmin(admin.ModelAdmin):
    list_display = ('user', 'purchased_at', 'expires_at', 'amount', 'duration_minutes', 'multiplier', 'status', 'reference', 'receiver_wallet')
    list_filter = ('purchased_at', 'expires_at', 'status')
    search_fields = ('user__username', 'reference', 'tx_signature')
    readonly_fields = ('reference', 'tx_signature')

    actions = ('mark_as_completed', 'mark_as_failed')

    def mark_as_completed(self, request, queryset):
        """Admin action: mark selected purchases as completed and apply boost to the user."""
        applied = 0
        for purchase in queryset:
            if purchase.status == 'completed':
                continue
            purchase.status = 'completed'
            if not purchase.purchased_at:
                purchase.purchased_at = timezone.now()
            if not purchase.expires_at:
                purchase.expires_at = timezone.now() + timedelta(minutes=purchase.duration_minutes or 0)
            purchase.save()

            # ensure the user has a Miner and apply boost flag
            try:
                miner = purchase.user.miner
            except Miner.DoesNotExist:
                miner = Miner.objects.create(user=purchase.user)
            miner.is_boosted = True
            miner.save()
            applied += 1

        self.message_user(request, f"Marked {applied} purchase(s) as completed and applied boosts.", level=messages.SUCCESS)
    mark_as_completed.short_description = "Mark selected purchases as completed and apply boost"

    def mark_as_failed(self, request, queryset):
        """Admin action: mark selected purchases as failed."""
        updated = queryset.update(status='failed')
        self.message_user(request, f"Marked {updated} purchase(s) as failed.", level=messages.WARNING)
    mark_as_failed.short_description = "Mark selected purchases as failed"


@admin.register(SolanaWallet)
class SolanaWalletAdmin(admin.ModelAdmin):
    list_display = ('address', 'label', 'active', 'created_at')
    list_filter = ('active',)
    search_fields = ('address', 'label')


@admin.register(Donation)
class DonationAdmin(admin.ModelAdmin):
    list_display = ('reference', 'user', 'sol_amount', 'receiver_wallet', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('reference', 'user__username', 'tx_signature')
    readonly_fields = ('reference', 'tx_signature', 'created_at')
