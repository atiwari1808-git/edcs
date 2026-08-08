import secrets
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest
from django.shortcuts import redirect
from django.conf import settings
from . import client


@login_required
def graph_login(request):
    if settings.GRAPH_MOCK:
        return redirect("/scheduler/")
    state = secrets.token_urlsafe(16)
    request.session["graph_state"] = state
    return redirect(client.auth_url(state))


@login_required
def graph_callback(request):
    if request.GET.get("state") != request.session.pop("graph_state", None):
        return HttpResponseBadRequest("state mismatch")
    code = request.GET.get("code")
    if not code:
        return HttpResponseBadRequest("missing code")
    client.redeem_code(request.user, code)
    return redirect(request.session.pop("post_graph_redirect", "/scheduler/"))
