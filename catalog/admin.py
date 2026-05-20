from django.contrib import admin
from django.utils.html import format_html

from .models import (
    CircleChart,
    Config,
    IceCreamLogo,
    TasteTags,
    Line,
    Product,
    ProductCriteriaReview,
    ProductIceCreamLogo,
    ProductReview,
    ProductTasteCriteria,
    ProductTasting,
    ProductTastingUserMark,
    TasteCriteria,
    Tasting,
    TastingParticipation,
)


@admin.register(Line)
class LineAdmin(admin.ModelAdmin):
    list_display = ("id", "name")
    search_fields = ("name", "id")
    ordering = ("name",)


@admin.register(TasteTags)
class IceCreamTasteTagsAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "weight")
    list_editable = ("weight",)
    search_fields = ("name", "id")
    ordering = ("name",)


@admin.register(IceCreamLogo)
class IceCreamLogoAdmin(admin.ModelAdmin):
    list_display = ("id", "text", "thumb")
    search_fields = ("text", "id")
    readonly_fields = ("thumb",)

    @admin.display(description="Превью")
    def thumb(self, obj: IceCreamLogo):
        if not obj.image:
            return "—"
        return format_html('<img src="{}" style="height:40px;border-radius:4px"/>', obj.image.url)


@admin.register(CircleChart)
class CircleChartAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "name")
    list_editable = ("order",)
    search_fields = ("name", "id")
    ordering = ("order", "id")


@admin.register(TasteCriteria)
class TasteCriteriaAdmin(admin.ModelAdmin):
    list_display = ("id", "order", "name", "orientation", "chart", "grade")
    list_editable = ("order", "orientation", "chart")
    list_filter = ("orientation", "chart")
    search_fields = ("name", "id")
    autocomplete_fields = ("chart",)
    ordering = ("order", "id")


class ProductIceCreamLogoInline(admin.TabularInline):
    model = ProductIceCreamLogo
    extra = 0
    autocomplete_fields = ("logo",)


class ProductTasteCriteriaInline(admin.TabularInline):
    model = ProductTasteCriteria
    extra = 0
    autocomplete_fields = ("criteria",)


class ProductInTastingsInline(admin.TabularInline):
    model = ProductTasting
    extra = 0
    fk_name = "product"
    autocomplete_fields = ("tasting",)
    fields = ("tasting", "category", "order", "tea_flavor_combination")
    ordering = ("tasting__date",)
    verbose_name = "Дегустация"
    verbose_name_plural = "В каких дегустациях"


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("number", "name", "type", "line", "thumb")
    list_display_links = ("number", "name")
    list_filter = ("type", "line", "taste_tags")
    search_fields = ("name", "number", "id")
    autocomplete_fields = ("line",)
    filter_horizontal = ("taste_tags",)
    readonly_fields = ("thumb",)
    ordering = ("type", "number", "name")
    fieldsets = (
        (None, {"fields": ("type", "number", "name", "line")}),
        ("Контент", {"fields": ("description", "interesting_fact", "composition", "image", "thumb", "color")}),
        (
            "Чай",
            {
                "classes": ("collapse",),
                "fields": (
                    "tea_nickname",
                    "tea_sort",
                    "tea_index",
                    "tea_price_per_gram",
                    "tea_plucking_season",
                ),
            },
        ),
        ("Результат", {"fields": ("result_phrase",)}),
        ("Теги", {"fields": ("taste_tags",)}),
    )
    inlines = [ProductIceCreamLogoInline, ProductTasteCriteriaInline, ProductInTastingsInline]

    @admin.display(description="Превью")
    def thumb(self, obj: Product):
        if not obj.image:
            return "—"
        return format_html('<img src="{}" style="height:48px;border-radius:4px"/>', obj.image.url)


class TastingParticipationInline(admin.TabularInline):
    model = TastingParticipation
    extra = 0
    readonly_fields = ("joined_at",)
    autocomplete_fields = ("user",)


class ProductTastingInline(admin.TabularInline):
    model = ProductTasting
    extra = 0
    autocomplete_fields = ("product", "tea_flavor_combination")
    fields = ("product", "category", "order", "tea_flavor_combination")
    ordering = ("order",)


class TastingUserMarksInline(admin.TabularInline):
    model = ProductTastingUserMark
    fk_name = "tasting"
    extra = 0
    can_delete = False
    fields = ("user", "product_tasting", "is_nominated", "podium_place", "updated_at")
    readonly_fields = ("user", "product_tasting", "is_nominated", "podium_place", "updated_at")
    ordering = ("podium_place", "-updated_at")
    verbose_name = "Метка пользователя"
    verbose_name_plural = "Номинации и подиумы (read-only)"

    def has_add_permission(self, request, obj=None):
        return False

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("user", "product_tasting__product")


@admin.register(Tasting)
class TastingAdmin(admin.ModelAdmin):
    list_display = ("title", "type", "date", "products_count", "participants_count")
    list_filter = ("type", "date")
    search_fields = ("title", "id")
    date_hierarchy = "date"
    inlines = [ProductTastingInline, TastingParticipationInline, TastingUserMarksInline]

    def get_queryset(self, request):
        from django.db.models import Count

        return (
            super()
            .get_queryset(request)
            .annotate(_products=Count("products", distinct=True), _participants=Count("participants", distinct=True))
        )

    @admin.display(description="Продуктов", ordering="_products")
    def products_count(self, obj):
        return obj._products

    @admin.display(description="Участников", ordering="_participants")
    def participants_count(self, obj):
        return obj._participants


@admin.register(ProductTasting)
class ProductTastingAdmin(admin.ModelAdmin):
    list_display = ("tasting", "product", "category", "order")
    list_filter = ("tasting", "category")
    search_fields = ("product__name", "product__id", "tasting__title", "tasting__id", "category", "id")
    autocomplete_fields = ("product", "tasting", "tea_flavor_combination")
    ordering = ("tasting", "order")
    fields = ("tasting", "product", "category", "order", "tea_flavor_combination")


class ProductCriteriaReviewInline(admin.TabularInline):
    model = ProductCriteriaReview
    extra = 0
    autocomplete_fields = ("criteria",)


@admin.register(ProductReview)
class ProductReviewAdmin(admin.ModelAdmin):
    list_display = ("user", "product", "tasted", "is_bookmarked", "updated_at")
    list_editable = ("tasted", "is_bookmarked")
    list_filter = ("tasted", "is_bookmarked", "updated_at", "taste_tags")
    search_fields = (
        "id",
        "user__username",
        "user__phone",
        "user__first_name",
        "user__id",
        "product__name",
        "product__id",
    )
    autocomplete_fields = ("user", "product")
    filter_horizontal = ("taste_tags",)
    readonly_fields = ("created_at", "updated_at")
    inlines = [ProductCriteriaReviewInline]
    fieldsets = (
        (None, {"fields": ("user", "product")}),
        ("Состояние", {"fields": ("tasted", "is_bookmarked")}),
        ("Отзыв", {"fields": ("global_comment", "self_comment", "composition", "taste_tags")}),
        ("Служебное", {"fields": ("created_at", "updated_at")}),
    )


@admin.register(ProductTastingUserMark)
class ProductTastingUserMarkAdmin(admin.ModelAdmin):
    list_display = ("user", "product_display", "tasting", "is_nominated", "podium_place", "updated_at")
    list_editable = ("is_nominated", "podium_place")
    list_filter = ("tasting", "is_nominated", "podium_place")
    search_fields = (
        "id",
        "user__username",
        "user__phone",
        "user__first_name",
        "user__id",
        "product_tasting__product__name",
        "product_tasting__product__id",
        "product_tasting__id",
        "tasting__title",
        "tasting__id",
    )
    autocomplete_fields = ("user", "product_tasting", "tasting")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (None, {"fields": ("user", "product_tasting", "tasting")}),
        ("Метки", {"fields": ("is_nominated", "podium_place")}),
        ("Служебное", {"fields": ("created_at", "updated_at")}),
    )
    ordering = ("tasting", "podium_place", "-updated_at")

    @admin.display(description="Продукт", ordering="product_tasting__product__name")
    def product_display(self, obj: ProductTastingUserMark):
        return obj.product_tasting.product

    def get_queryset(self, request):
        return (
            super()
            .get_queryset(request)
            .select_related("user", "tasting", "product_tasting__product")
        )


@admin.register(Config)
class ConfigAdmin(admin.ModelAdmin):
    list_display = ("__str__", "show_share_link")
    fields = ("show_share_link", "share_text")

    def has_add_permission(self, request):
        return not Config.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False
