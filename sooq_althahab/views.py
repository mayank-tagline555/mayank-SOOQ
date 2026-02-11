from datetime import timedelta

from django.conf import settings
from django.db.models import F
from django.db.models import Max
from django.db.models import Min
from django.db.models import Window
from django.db.models.functions import ExtractWeekDay
from django.db.models.functions import RowNumber
from django.db.models.functions import TruncDate
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from account.message import MESSAGES
from sooq_althahab.messages import MESSAGES as SOOQ_ALTHAHAB_MESSAGES
from sooq_althahab.utils import generic_response
from sooq_althahab_admin.models import MetalPriceHistory
from sooq_althahab_admin.serializers import MetalPriceHistoryChartSerializer

from .utils import s3


class GeneratePresignedS3URLAPIView(APIView):
    """
    This view generates presigned URLs for uploading multiple files to an S3 bucket.

    When a POST request is made, it expects a JSON body with:
        - 'bucket_name': Name of the S3 bucket (required).
        - 'files': A list of dictionaries, each containing:
            - 'name': File name (required).
            - 'content_type': MIME type of the file (required).

    Response:
        - JSON object mapping file names to their respective presigned URLs.
        - If an error occurs, a JSON object with an 'error' message.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        try:
            data = request.data
            file_data = {}
            bucket_name = data.get("bucket_name")

            if not bucket_name:
                return generic_response(
                    error_message=MESSAGES["bucket_name_required"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            files = data.get("files", [])
            if not files:
                return generic_response(
                    error_message=MESSAGES["file_names_required"],
                    status_code=status.HTTP_400_BAD_REQUEST,
                )

            # Generate presigned URLs for each file and store them in a dictionary.
            for file in files:
                # Generate a presigned URL for each file.
                file_name = file.get("name")
                content_type = file.get("content_type")

                presigned_url = s3.generate_presigned_url(
                    "put_object",
                    Params={
                        "Bucket": bucket_name,
                        "Key": file_name,
                        "ContentType": content_type,
                    },
                    ExpiresIn=settings.S3_PRESIGNED_PUT_URL_EXPIRATION_DURATION,
                )
                file_data[file_name] = presigned_url

            # Return a response containing the list of file data.
            return generic_response(
                file_data,
                status_code=status.HTTP_200_OK,
            )

        except Exception as e:
            return generic_response(
                error_message=str(e), status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class PreciousMetalPriceListAPIView(ListAPIView):
    """
    API View to return daily candlestick data (open, close, high, low) for each metal
    for the last 7 business days (excluding weekends). This is used to plot charts
    like OHLC/Candlestick charts.

    Each day's data per metal includes:
    - open_price: First price of the day
    - close_price: Last price of the day
    - high_price: Maximum price of the day
    - low_price: Minimum price of the day

    Note: Weekends (Saturday and Sunday) are excluded as markets are closed
    and there's no price fluctuation during these days.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = MetalPriceHistoryChartSerializer

    def get_queryset(self):
        """
        Build candlestick (OHLC) data for each metal for the last 7 business days (excluding weekends).
        Strategy:
        1. Compute "open" and "close" prices using row numbers (first and last record per day).
        2. Compute "high" and "low" prices using simple aggregations.
        3. Merge results from both steps into a single dictionary keyed by (metal, date).
        4. Return the merged results as a sorted list of dictionaries.
        """

        if self.request.user.is_anonymous:
            return MetalPriceHistory.objects.none()

        # Define date range: get last 7 business days (excluding weekends)
        current_time = timezone.now()

        # Calculate start date to ensure we get 7 business days
        # Start from 10 days ago to account for weekends
        start_date = (current_time - timedelta(days=8)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        # ---- STEP 1: Find OPEN and CLOSE prices using row numbers ----
        # - "open price" = first price of the day (earliest created_at)
        # - "close price" = last price of the day (latest created_at)
        # We use ROW_NUMBER() window function partitioned by (metal, day).
        with_row_numbers = (
            MetalPriceHistory.objects.annotate(
                created_date=TruncDate("created_at"),
                weekday=ExtractWeekDay("created_at"),
            )
            .filter(created_at__gte=start_date, created_at__lte=current_time)
            .exclude(weekday__in=[1, 7])  # exclude Sunday=1, Saturday=7
            .annotate(
                raw_number_first=Window(  # row number for "open" candidate
                    expression=RowNumber(),
                    partition_by=[F("global_metal_id"), TruncDate("created_at")],
                    order_by=F("created_at").asc(),
                ),
                raw_number_last=Window(  # row number for "close" candidate
                    expression=RowNumber(),
                    partition_by=[F("global_metal_id"), TruncDate("created_at")],
                    order_by=F("created_at").desc(),
                ),
            )
        )

        # Keep only the first row of each (metal, day) → open price
        open_prices = (
            with_row_numbers.filter(raw_number_first=1)
            .values("global_metal_id", "created_date")
            .annotate(open_price=F("price"))
        )

        # Keep only the last row of each (metal, day) → close price
        close_prices = (
            with_row_numbers.filter(raw_number_last=1)
            .values("global_metal_id", "created_date")
            .annotate(close_price=F("price"))
        )

        # ---- STEP 2: Find HIGH and LOW prices using simple aggregation ----
        # - "high price" = maximum price of the day
        # - "low price" = minimum price of the day
        # This part does not require window functions.
        highs_lows = (
            MetalPriceHistory.objects.annotate(
                created_date=TruncDate("created_at"),
                weekday=ExtractWeekDay("created_at"),
            )
            .filter(created_at__gte=start_date, created_at__lte=current_time)
            .exclude(weekday__in=[1, 7])  # exclude Sunday=1, Saturday=7
            .values("global_metal_id", "created_date")
            .annotate(
                high_price=Max("price"),
                low_price=Min("price"),
                global_metal_name=F("global_metal__name"),
                metal_symbol=F("global_metal__symbol"),
            )
        )

        # ---- STEP 3: Merge open, close, high, low into one dictionary ----
        # Key: (metal_id, date)
        # Value: dict with open, close, high, low, and metal info
        candlestick_data = {}
        for row in highs_lows:
            key = (row["global_metal_id"], row["created_date"])
            candlestick_data[key] = row

        for row in open_prices:
            key = (row["global_metal_id"], row["created_date"])
            candlestick_data[key]["open_price"] = row["open_price"]

        for row in close_prices:
            key = (row["global_metal_id"], row["created_date"])
            candlestick_data[key]["close_price"] = row["close_price"]

        # ---- STEP 4: Return sorted list for readability ----
        # Sort first by date, then by metal name.
        return sorted(
            candlestick_data.values(),
            key=lambda row: (row["created_date"], row["global_metal_name"]),
        )

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        serializer = self.get_serializer(queryset, many=True)
        return generic_response(
            data=serializer.data,
            message=SOOQ_ALTHAHAB_MESSAGES["precious_metal_price_history_retrieved"],
            status_code=status.HTTP_200_OK,
        )
