from django.contrib.auth.decorators import user_passes_test
from django.shortcuts import redirect, render


def home(request):
    if request.user.is_authenticated:
        # The monitors dashboard is the app's home.
        return redirect("monitors:list")
    else:
        return render(request, "web/landing_page.html")


@user_passes_test(lambda u: u.is_superuser)
def simulate_error(request):
    raise Exception("This is a simulated error.")
