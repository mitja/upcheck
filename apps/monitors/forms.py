from django import forms
from django.core.exceptions import ValidationError

from .checks import BlockedTarget, TargetResolutionError, ensure_allowed_target
from .models import Monitor
from .plans import allowed_intervals, plan_for


class MonitorForm(forms.ModelForm):
    class Meta:
        model = Monitor
        fields = ["name", "url", "interval_minutes", "timeout_seconds", "is_active", "is_public"]

    def __init__(self, *args, user, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user
        self.plan = plan_for(user)
        self.fields["interval_minutes"].choices = allowed_intervals(self.plan, Monitor.Interval.choices)
        self.fields["timeout_seconds"].validators = []
        self.fields["timeout_seconds"].widget.attrs.update({"min": 1, "max": 30})

    def clean_url(self):
        url = self.cleaned_data["url"]
        try:
            ensure_allowed_target(url)
        except BlockedTarget as e:
            raise ValidationError(f"This target is not allowed: {e}.") from e
        except TargetResolutionError:
            raise ValidationError("This hostname could not be resolved.") from None
        return url

    def clean_interval_minutes(self):
        interval = self.cleaned_data["interval_minutes"]
        if interval < self.plan.min_interval_minutes:
            raise ValidationError(
                f"The {self.plan.name} plan allows intervals of {self.plan.min_interval_minutes} minutes or more."
            )
        return interval

    def clean_timeout_seconds(self):
        timeout = self.cleaned_data["timeout_seconds"]
        if not 1 <= timeout <= 30:
            raise ValidationError("Timeout must be between 1 and 30 seconds.")
        return timeout

    def clean(self):
        cleaned = super().clean()
        if self.instance.pk is None:
            monitor_count = self.user.monitors.count()
            if monitor_count >= self.plan.max_monitors:
                raise ValidationError(
                    f"The {self.plan.name} plan allows up to {self.plan.max_monitors} monitors. Upgrade to add more."
                )
        return cleaned
