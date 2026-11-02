from django.contrib.auth.decorators import login_required
from django.http import JsonResponse

from shop.models import Order


@login_required
def list_orders(request):
    orders = Order.objects.filter(owner=request.user)
    return JsonResponse({"orders": [o.id for o in orders]})
