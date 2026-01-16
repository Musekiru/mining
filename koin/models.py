import uuid
from django.db import models
from django.contrib.auth.models import User


from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
from datetime import timedelta
from django.db.models import Max

class Miner(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    balance = models.DecimalField(max_digits=12, decimal_places=6, default=0)
    last_mined = models.DateTimeField(null=True, blank=True)
    is_boosted = models.BooleanField(default=False)
    # whether the user currently has the mining page open (controls accrual)
    is_mining = models.BooleanField(default=False)
    # Optional per-user base rate (units per second). If set, overrides the global base.
    custom_rate = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True,
                                      help_text='Optional custom base mining rate (units per second) for this user')

    def mining_rate(self):
        # Prefer active BoostPurchase records when deciding boosted rate.
        try:
            # find the highest multiplier among active boosts for this user
            active_qs = BoostPurchase.objects.filter(user=self.user, expires_at__gt=timezone.now())
            max_mult = active_qs.aggregate(m=Max('multiplier'))['m']
            if max_mult:
                base = self.custom_rate if self.custom_rate is not None else Decimal('0.0019')
                return base * Decimal(str(max_mult))
            active = False
        except NameError:
            # BoostPurchase not defined yet during import; fall back to is_boosted
            active = self.is_boosted

        if active:
            # default boosted fallback
            return Decimal('0.002')

        # Unboosted mining rate: use custom_rate if set otherwise default 0.0019 units/sec
        return self.custom_rate if self.custom_rate is not None else Decimal('0.0019')
    
    def __str__(self):
        return f"{self.user.username} (Miner)"



class Minercount(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    referral_code = models.CharField(max_length=12, unique=True, blank=True)
    referred_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="referrals"
    )
    referral_count = models.PositiveIntegerField(default=0)
    balance = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    def save(self, *args, **kwargs):
        if not self.referral_code:
            self.referral_code = uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.username} - {self.referral_code}"


class BoostPurchase(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    purchased_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    amount = models.DecimalField(max_digits=8, decimal_places=2)
    duration_minutes = models.PositiveIntegerField()
    # multiplier (e.g., 3 for 3x, 6 for 6x)
    multiplier = models.PositiveIntegerField(default=1)
    # payment tracking
    reference = models.CharField(max_length=64, unique=True, blank=True)
    tx_signature = models.CharField(max_length=128, blank=True, null=True)
    status = models.CharField(max_length=16, choices=(
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ), default='pending')
    # which configured Solana wallet was used for this purchase (optional)
    receiver_wallet = models.ForeignKey('SolanaWallet', on_delete=models.SET_NULL, null=True, blank=True)

    def is_active(self):
        return self.expires_at > timezone.now()

    def __str__(self):
        return f"{self.user.username} boost until {self.expires_at.strftime('%Y-%m-%d %H:%M')}"


class Donation(models.Model):
    """Record of a user donation (sent via Solana)."""
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    # amount in SOL (optional - user can enter SOL directly)
    sol_amount = models.DecimalField(max_digits=16, decimal_places=8, null=True, blank=True)
    # optional USD amount or note
    note = models.CharField(max_length=255, blank=True)
    reference = models.CharField(max_length=64, unique=True, blank=True)
    tx_signature = models.CharField(max_length=128, blank=True, null=True)
    status = models.CharField(max_length=16, choices=(
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
    ), default='pending')
    receiver_wallet = models.ForeignKey('SolanaWallet', on_delete=models.SET_NULL, null=True, blank=True)

    def __str__(self):
        who = self.user.username if self.user else 'anonymous'
        return f"Donation {self.reference} by {who} ({self.sol_amount or 'unknown'} SOL)"


class SiteSetting(models.Model):
    """Simple key/value site settings editable in the admin.

    We'll use a setting with key='estimated_value' to store the string shown
    in the UI (for example: "+0.01 / click").
    """
    key = models.CharField(max_length=64, unique=True)
    value = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = "Site setting"
        verbose_name_plural = "Site settings"

    def __str__(self):
        return f"{self.key}: {self.value}"


class SolanaWallet(models.Model):
    """A Solana receiver wallet that can be managed in admin.

    Admins can add many wallets and mark them active. During a purchase
    one active wallet will be chosen and displayed as the receiver.
    """
    address = models.CharField(max_length=128, unique=True)
    label = models.CharField(max_length=128, blank=True)
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        if self.label:
            return f"{self.label} — {self.address}"
        return self.address


class MinerRateChange(models.Model):
    """Audit log for per-user mining rate changes."""
    miner = models.ForeignKey(Miner, on_delete=models.CASCADE, related_name='rate_changes')
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    old_rate = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    new_rate = models.DecimalField(max_digits=12, decimal_places=6, null=True, blank=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ('-changed_at',)

    def __str__(self):
        who = self.changed_by.username if self.changed_by else 'system'
        return f"{self.miner.user.username}: {self.old_rate} -> {self.new_rate} by {who} at {self.changed_at.strftime('%Y-%m-%d %H:%M')}"
