from django.urls import path
from rest_framework.routers import DefaultRouter

from .views import ConfigView, ResultViewSet, TastingViewSet

router = DefaultRouter()
router.register("tastings", TastingViewSet, basename="tasting")
router.register("results", ResultViewSet, basename="result")

app_name = "catalog"

urlpatterns = router.urls + [
    path("config/", ConfigView.as_view(), name="config"),
]
