from rest_framework.routers import DefaultRouter

from .views import ProductViewSet, TastingViewSet

router = DefaultRouter()
router.register("products", ProductViewSet, basename="product")
router.register("tastings", TastingViewSet, basename="tasting")

app_name = "catalog"

urlpatterns = router.urls
