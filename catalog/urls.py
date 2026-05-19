from rest_framework.routers import DefaultRouter

from .views import ProductViewSet, ResultViewSet, TastingViewSet

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("tastings", TastingViewSet, basename="tasting")
router.register("results", ResultViewSet, basename="result")

app_name = "catalog"

urlpatterns = router.urls
