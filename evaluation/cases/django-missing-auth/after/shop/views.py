from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt

from shop.models import Order


@login_required
def list_orders(request):
    orders = Order.objects.filter(owner=request.user)
    return JsonResponse({"orders": [o.id for o in orders]})


@csrf_exempt
def delete_order(request, order_id):
    Order.objects.get(pk=order_id).delete()
    return JsonResponse({"deleted": order_id})
