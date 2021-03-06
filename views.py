from django.utils import timezone

from rest_framework.generics import GenericAPIView
from rest_framework.response import Response
from rest_framework import permissions

import json
import datetime
from urllib.parse import quote_plus

from .utils import order_data, remove_order_data
from .utils import sign as sign_func
from .utils import urlencode_data as urlencode_data_func
from .utils import check_sign as check_sign_func
from .utils import check_ali_sign as check_ali_sign_func

from .config import NOTIFY_URL, APP_ID, RSA_PRIVATE, ALIPAY_PUBLIC_KEY, PAY_URL

from .models import Order, Refund
from .serializers import OrderSerializer, RefundSerializer


# 获取签名
class SignView(GenericAPIView):
    serializer_class = OrderSerializer
    permission_classes = (permissions.IsAuthenticated,)

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = self.request.user
        instance = Order.objects.create(**request.data)
        instance.out_trade_no = timezone.now().strftime('%Y%m%d') +'{}'.format(instance.id)
        instance.save()

        subject = serializer.validated_data.get('subject')
        total_amount = serializer.validated_data.get('total_amount')

        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        notify_url = NOTIFY_URL
        app_id = APP_ID

        biz_content = {
            'subject': subject,
            'total_amount': '%.2f' % float(total_amount),
            'product_code': 'QUICK_MSECURITY_PAY',
            'out_trade_no': instance.out_trade_no,
        }

        payload = {
            'app_id': app_id,
            'method': 'alipay.trade.app.pay',
            'charset': 'UTF-8',
            'format': 'json',
            'sign_type': 'RSA2',
            'timestamp': timestamp,
            'version': '1.0',
            'notify_url': notify_url,
            'biz_content': json.dumps(biz_content, separators=(',', ':')),
        }

        private_key = RSA_PRIVATE

        # 对payload转化成key+value&对，并且排序
        order_payload = order_data(payload)
        # print('order', order_payload)

        # 根据排序好的数据获取签名
        sign = sign_func(order_payload, private_key)
        # print('sign', sign)
        
        # 获取urlencode签名数据
        urlencode_data = urlencode_data_func(payload, sign)

        return Response({'sign': urlencode_data})


# 支付宝通知
class PayNotifyView(GenericAPIView):

    def post(self, request, *args, **kwargs):
        sign = request.data.get('sign')

        payload = remove_order_data(request.data)

        alipay_public_key = ALIPAY_PUBLIC_KEY

        is_checked = check_ali_sign_func(payload, sign, alipay_public_key)
        if not is_checked:
            return Response('fail')

        total_amount = float(request.data.get('total_amount'))
        out_trade_no = request.data.get('out_trade_no')
        trade_no = request.data.get('trade_no')

        order = Order.objects.filter(out_trade_no=out_trade_no).first()
        if order and order.status == 1:
            return Response('success')

        if order and order.status == 0:
            if "%s" % order.total_amount == "%s" % total_amount:
                order.trade_no = trade_no
                order.status = True
                order.save()

        return Response('success')  # 有效数据需要返回 'success' 给 alipay
    
class RefundView(GenericAPIView):
    serializer_class = RefundSerializer
    permission_classes = (permissions.AllowAny,)

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        # user = self.request.user
        instance = Refund.objects.create(**request.data)
        instance.out_refund_no = 'alipay-refund' + timezone.now().strftime('%Y%m%d') + \
            '%s' % instance.id
        instance.save()

        out_trade_no = serializer.validated_data['out_trade_no']
        refund_amount = serializer.validated_data['refund_amount']
        refund_reason = serializer.validated_data.get('refund_reason')

        biz_content = {
            'refund_reason': refund_reason,
            'refund_amount': '%.2f' % float(refund_amount),
            'out_trade_no': out_trade_no,
        }

        timestamp = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        app_id = settings.ALIPAY['APP_ID']

        payload = {
            'app_id': app_id,
            'method': 'alipay.trade.refund',
            'charset': 'utf-8',
            'sign_type': 'RSA2',
            'timestamp': timestamp,
            'version': '1.0',
            'biz_content': json.dumps(biz_content, separators=(',', ':'))
        }

        private_key = settings.RSA_PRIVATE

        # 对payload转化成key+value&对，并且排序
        order_payload = order_data(payload)

        # 根据排序好的数据获取签名
        sign = sign_func(order_payload, private_key)

        urlencode_data = urlencode_data_func(payload, sign)

        url = PAY_URL.replace('payload', urlencode_data)

        req_obj = requests.get(url).json()
        if req_obj['alipay_trade_refund_response']['code'] == '10000':
            instance.status = "1"
            instance.trade_no = req_obj['alipay_trade_refund_response']['trade_no']
            instance.save()

        # print('req_obj: {}'.format(req_obj))
        return Response({'message': 'ok'})
