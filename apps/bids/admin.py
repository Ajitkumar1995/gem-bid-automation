from django.contrib import admin
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.admin import UserAdmin
from django.contrib.admin.sites import NotRegistered

from .limits import get_active_bid_count, get_default_bid_limit, get_effective_bid_limit
from .models import Bid, BidLimitAudit, BidRetentionPolicy, BidSystemSettings

@admin.register(Bid)
class BidAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "bid_number", "status", "uploaded_by", "created_at")
    list_filter = ("status", "source", "created_at")
    search_fields = ("title", "bid_number", "uploaded_by__username")
    readonly_fields = ("created_at", "updated_at", "extracted_metadata")


class BidRetentionPolicyAdminForm(forms.ModelForm):
    change_reason = forms.CharField(required=False, max_length=500, help_text="Optional audit note for this limit change.")

    class Meta:
        model = BidRetentionPolicy
        fields = ("user", "bid_limit")


@admin.register(BidRetentionPolicy)
class BidRetentionPolicyAdmin(admin.ModelAdmin):
    list_display = ("user", "active_bid_count", "effective_limit", "remaining_slots", "limit_status")
    search_fields = ("user__username", "user__email")
    ordering = ("user__username",)
    fields = ("user", "bid_limit", "change_reason")
    form = BidRetentionPolicyAdminForm

    def get_readonly_fields(self, request, obj=None):
        return ("user",) if obj else ()

    def save_model(self, request, obj, form, change):
        old_limit = get_effective_bid_limit(obj.user)
        super().save_model(request, obj, form, change)
        new_limit = get_effective_bid_limit(obj.user)
        if old_limit != new_limit:
            BidLimitAudit.objects.create(
                user=obj.user,
                changed_by=request.user,
                old_limit=old_limit,
                new_limit=new_limit,
                reason=form.cleaned_data.get("change_reason", ""),
            )

    @admin.display(description="Active bids")
    def active_bid_count(self, obj):
        return get_active_bid_count(obj.user)

    @admin.display(description="Effective limit")
    def effective_limit(self, obj):
        return get_effective_bid_limit(obj.user)

    @admin.display(description="Slots remaining")
    def remaining_slots(self, obj):
        return max(0, get_effective_bid_limit(obj.user) - get_active_bid_count(obj.user))

    @admin.display(description="Status")
    def limit_status(self, obj):
        return "Limit reached" if get_active_bid_count(obj.user) >= get_effective_bid_limit(obj.user) else "Available"

    def delete_model(self, request, obj):
        old_limit = get_effective_bid_limit(obj.user)
        user = obj.user
        super().delete_model(request, obj)
        new_limit = get_default_bid_limit()
        if old_limit != new_limit:
            BidLimitAudit.objects.create(
                user=user,
                changed_by=request.user,
                old_limit=old_limit,
                new_limit=new_limit,
                reason="Per-user override removed; reset to site default.",
            )


@admin.register(BidSystemSettings)
class BidSystemSettingsAdmin(admin.ModelAdmin):
    list_display = ("default_bid_limit", "active_bid_expiry_days")
    fields = ("default_bid_limit", "active_bid_expiry_days")

    def has_add_permission(self, request):
        return not BidSystemSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(BidLimitAudit)
class BidLimitAuditAdmin(admin.ModelAdmin):
    list_display = ("created_at", "changed_by", "user", "old_limit", "new_limit", "reason")
    list_filter = ("created_at",)
    search_fields = ("user__username", "changed_by__username", "reason")
    readonly_fields = ("created_at", "changed_by", "user", "old_limit", "new_limit", "reason")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


User = get_user_model()
try:
    admin.site.unregister(User)
except NotRegistered:
    pass


@admin.register(User)
class UserBidLimitAdmin(UserAdmin):
    list_display = UserAdmin.list_display + ("active_bids", "bid_limit", "remaining_bid_slots")

    @admin.display(description="Active bids")
    def active_bids(self, obj):
        return get_active_bid_count(obj)

    @admin.display(description="Bid limit")
    def bid_limit(self, obj):
        return get_effective_bid_limit(obj)

    @admin.display(description="Slots remaining")
    def remaining_bid_slots(self, obj):
        return max(0, get_effective_bid_limit(obj) - get_active_bid_count(obj))
