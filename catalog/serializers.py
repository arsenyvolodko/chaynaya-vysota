from decimal import ROUND_HALF_UP, Decimal

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from .models import (
    IceCreamLogo,
    IceCreamTasteTags,
    Product,
    ProductReview,
    ProductTastingUserMark,
    TasteCriteria,
    Tasting,
    TastingParticipation,
)

GRADE_SCHEMA = {
    "type": "array",
    "description": (
        "Шкала оценки как упорядоченный список пар {value, label}. "
        "Список — чтобы сохранять порядок отображения в админке/фронте и допускать дубли "
        "value (две разные подписи на одно и то же числовое значение)."
    ),
    "items": {
        "type": "object",
        "properties": {
            "value": {"type": "integer", "description": "Числовое значение оценки."},
            "label": {"type": "string", "description": "Человекочитаемая подпись."},
        },
        "required": ["value", "label"],
    },
}

TASTE_CRITERIA_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "grade": GRADE_SCHEMA,
            "for_tea_combination": {
                "type": "boolean",
                "description": "Признак с through-модели ProductTasteCriteria: применяется ли этот критерий "
                "к оценке сочетания с чаем для данного продукта.",
            },
            "user_grade_review": {
                "type": "integer",
                "nullable": True,
                "description": "Оценка текущего пользователя по критерию; null, если он не оценивал.",
            },
        },
        "required": ["id", "name", "grade", "for_tea_combination", "user_grade_review"],
    },
}

USER_COMPOSITION_SCHEMA = {
    "type": "array",
    "items": {"type": "string"},
    "nullable": True,
    "description": "Личный состав текущего пользователя; null, если он ещё не оставлял отзыв.",
}

TEA_FLAVOR_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "string", "format": "uuid"},
            "name": {"type": "string"},
            "logo": {
                "type": "string",
                "format": "uri",
                "nullable": True,
                "description": "URL первого логотипа связного продукта; null, если у продукта нет логотипов.",
            },
        },
        "required": ["id", "name", "logo"],
    },
    "description": (
        "Сочетания вкусов для данной дегустации: список связанных Product "
        "(M2M на ProductTasting.tea_flavor_combination), отдаётся как {id, name, logo}."
    ),
}

TASTE_TAGS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "name": {"type": "string"},
            "weight": {"type": "number", "minimum": -1, "maximum": 1},
            "marked": {
                "type": "boolean",
                "description": "true, если текущий пользователь выбрал этот тег.",
            },
        },
        "required": ["id", "name", "weight", "marked"],
    },
}

TASTING_MARKS_SCHEMA = {
    "type": "array",
    "items": {
        "type": "object",
        "properties": {
            "tasting_id": {"type": "string", "format": "uuid"},
            "tasting_title": {"type": "string"},
            "is_nominated": {"type": "boolean"},
            "podium_place": {"type": "integer", "nullable": True, "minimum": 1, "maximum": 3},
        },
        "required": ["tasting_id", "tasting_title", "is_nominated", "podium_place"],
    },
    "description": (
        "Контекстные метки текущего пользователя для продукта по конкретным дегустациям "
        "(номинация, место в топ-3). Пустой список для анонима и продукта вне дегустаций."
    ),
}


TOTAL_SCORE_SCHEMA = {
    "type": "integer",
    "nullable": True,
    "description": (
        "Суммарный балл текущего пользователя: сумма user_grade_review по критериям + "
        "сумма weight выбранных тегов; округляется до целого по правилам арифметического "
        "округления (HALF_UP). null — продукт не попробован; 0 — попробован, но ничего не оценено."
    ),
}


class IceCreamLogoSerializer(serializers.ModelSerializer):
    class Meta:
        model = IceCreamLogo
        fields = ["id", "image", "text"]


class ProductSerializer(serializers.ModelSerializer):
    line = serializers.SerializerMethodField()
    logos = IceCreamLogoSerializer(many=True, read_only=True)
    taste_criteria = serializers.SerializerMethodField()
    composition = serializers.ListField(child=serializers.CharField(), read_only=True)

    taste_tags = serializers.SerializerMethodField()

    tasted = serializers.SerializerMethodField()
    is_bookmarked = serializers.SerializerMethodField()
    is_reviewed = serializers.SerializerMethodField()
    self_comment = serializers.SerializerMethodField()
    global_comment = serializers.SerializerMethodField()
    user_composition = serializers.SerializerMethodField()
    total_score = serializers.SerializerMethodField()
    tasting_marks = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "type",
            "name",
            "number",
            "line",
            "description",
            "interesting_fact",
            "composition",
            "image",
            "logos",
            "taste_criteria",
            "taste_tags",
            "tasted",
            "is_bookmarked",
            "is_reviewed",
            "color",
            "result_phrase",
            "self_comment",
            "global_comment",
            "user_composition",
            "total_score",
            "tasting_marks",
        ]

    def _user_review(self, obj: Product):
        cached = obj.__dict__.get("_cached_user_review", "MISSING")
        if cached != "MISSING":
            return cached

        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            review = None
        else:
            prefetched = getattr(obj, "_user_reviews", None)
            if prefetched is not None:
                review = prefetched[0] if prefetched else None
            else:
                review = ProductReview.objects.filter(user=request.user, product=obj).first()

        obj.__dict__["_cached_user_review"] = review
        return review

    def get_tasted(self, obj: Product) -> bool:
        review = self._user_review(obj)
        return bool(review and review.tasted)

    def get_is_bookmarked(self, obj: Product) -> bool:
        review = self._user_review(obj)
        return bool(review and review.is_bookmarked)

    def get_is_reviewed(self, obj: Product) -> bool:
        review = self._user_review(obj)
        if review is None:
            return False
        if review.global_comment or review.self_comment:
            return True
        if review.composition:
            return True
        if list(review.criteria_reviews.all()):
            return True
        if list(review.taste_tags.all()):
            return True
        return False

    def get_self_comment(self, obj: Product) -> str | None:
        review = self._user_review(obj)
        return review.self_comment if review else None

    def get_global_comment(self, obj: Product) -> str | None:
        review = self._user_review(obj)
        return review.global_comment if review else None

    @extend_schema_field(USER_COMPOSITION_SCHEMA)
    def get_user_composition(self, obj: Product):
        review = self._user_review(obj)
        return review.composition if review else None

    def get_line(self, obj: Product) -> str | None:
        return obj.line.name if obj.line else None

    @extend_schema_field(TASTE_TAGS_SCHEMA)
    def get_taste_tags(self, obj: Product) -> list[dict]:
        review = self._user_review(obj)
        marked_ids: set[int] = set()
        if review:
            marked_ids = {t.pk for t in review.taste_tags.all()}
        return [
            {"id": t.pk, "name": t.name, "weight": t.weight, "marked": t.pk in marked_ids}
            for t in obj.taste_tags.all()
        ]

    @extend_schema_field(TOTAL_SCORE_SCHEMA)
    def get_total_score(self, obj: Product) -> int | None:
        review = self._user_review(obj)
        if not review:
            return None
        marks_sum = sum(cr.mark for cr in review.criteria_reviews.all())
        weights_sum = sum(t.weight for t in review.taste_tags.all())
        total = Decimal(str(marks_sum + weights_sum))
        return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))

    @extend_schema_field(TASTING_MARKS_SCHEMA)
    def get_tasting_marks(self, obj: Product) -> list[dict]:
        request = self.context.get("request")
        if not request or not request.user or not request.user.is_authenticated:
            return []

        pt_rows = obj.__dict__.get("_pt_for_marks")
        if pt_rows is not None:
            results = []
            for pt in pt_rows:
                for mark in getattr(pt, "_user_marks_list", []):
                    results.append({
                        "tasting_id": mark.tasting_id,
                        "tasting_title": pt.tasting.title,
                        "is_nominated": mark.is_nominated,
                        "podium_place": mark.podium_place,
                    })
            return results

        marks = ProductTastingUserMark.objects.filter(
            user=request.user, product_tasting__product=obj,
        ).select_related("tasting")
        return [
            {
                "tasting_id": m.tasting_id,
                "tasting_title": m.tasting.title,
                "is_nominated": m.is_nominated,
                "podium_place": m.podium_place,
            }
            for m in marks
        ]

    @extend_schema_field(TASTE_CRITERIA_SCHEMA)
    def get_taste_criteria(self, obj: Product) -> list[dict]:
        review = self._user_review(obj)
        marks: dict[int, int] = {}
        if review:
            marks = {cr.criteria_id: cr.mark for cr in review.criteria_reviews.all()}
        rows = obj.__dict__.get("_taste_criteria_rows")
        if rows is None:
            rows = list(obj.producttastecriteria_set.select_related("criteria").order_by("order", "id"))
        return [
            {
                "id": row.criteria_id,
                "name": row.criteria.name,
                "grade": row.criteria.grade,
                "for_tea_combination": row.for_tea_combination,
                "user_grade_review": marks.get(row.criteria_id),
            }
            for row in rows
        ]


class ProductReviewWriteSerializer(serializers.Serializer):
    global_comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    self_comment = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    composition = serializers.ListField(
        child=serializers.CharField(allow_blank=False),
        required=False,
        help_text="Личный состав, как его воспринял пользователь.",
    )
    criteria_marks = serializers.DictField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Оценки по критериям: ключ — id TasteCriteria (строка), значение — целая оценка.",
    )
    taste_tags = serializers.ListField(
        child=serializers.IntegerField(),
        required=False,
        help_text="Id вкусовых тегов (IceCreamTasteTags), которые пользователь хочет отметить.",
    )
    tasted = serializers.BooleanField(
        required=False,
        help_text="Явный флаг «попробовал». Авто-выставляется в true при любой осмысленной полезной нагрузке.",
    )
    is_bookmarked = serializers.BooleanField(
        required=False,
        help_text="Закладка/избранное на блюдо. Независима от tasted.",
    )


class ProductInTastingSerializer(ProductSerializer):
    tea_flavor_combination = serializers.SerializerMethodField()
    category = serializers.SerializerMethodField()
    is_nominated = serializers.SerializerMethodField()
    podium_place = serializers.SerializerMethodField()

    class Meta(ProductSerializer.Meta):
        fields = ProductSerializer.Meta.fields + [
            "tea_flavor_combination",
            "category",
            "is_nominated",
            "podium_place",
        ]

    @extend_schema_field(TEA_FLAVOR_SCHEMA)
    def get_tea_flavor_combination(self, obj: Product) -> list[dict]:
        combinations = obj.__dict__.get("_tea_flavor_combination", [])
        if not combinations:
            return []
        request = self.context.get("request")
        return [
            {
                "id": p.id,
                "name": p.name,
                "logo": _first_logo_url(p, request),
            }
            for p in combinations
        ]

    def get_category(self, obj: Product) -> str | None:
        return obj.__dict__.get("_category")

    def get_is_nominated(self, obj: Product) -> bool:
        mark = obj.__dict__.get("_current_tasting_mark")
        return bool(mark and mark.is_nominated)

    def get_podium_place(self, obj: Product) -> int | None:
        mark = obj.__dict__.get("_current_tasting_mark")
        return mark.podium_place if mark else None


def _first_logo_url(product: Product, request) -> str | None:
    logo = next(iter(product.logos.all()), None)
    if logo is None or not logo.image:
        return None
    url = logo.image.url
    return request.build_absolute_uri(url) if request is not None else url


class TastingListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tasting
        fields = ["id", "title", "description", "date"]


class TastingDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tasting
        fields = ["id", "title", "description", "result_description", "date"]


class TastingParticipationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TastingParticipation
        fields = ["tasting", "joined_at"]
        read_only_fields = ["tasting", "joined_at"]


class TastingResultPodiumItemSerializer(serializers.Serializer):
    place = serializers.IntegerField()
    id = serializers.UUIDField()
    name = serializers.CharField()
    number = serializers.IntegerField(allow_null=True)
    total_score = serializers.IntegerField(allow_null=True)


class TastingResultFavoriteItemSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()
    number = serializers.IntegerField(allow_null=True)


class TastingResultCriteriaItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    min_total = serializers.IntegerField()
    max_total = serializers.IntegerField()
    user_total = serializers.IntegerField()


class TastingResultTopTagItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    weight = serializers.FloatField()
    count = serializers.IntegerField()


class TastingResultTeaMatchSerializer(serializers.Serializer):
    tea_id = serializers.UUIDField()
    tea_name = serializers.CharField()
    tea_logo = serializers.CharField(allow_null=True)
    product_id = serializers.UUIDField()
    product_name = serializers.CharField()
    product_number = serializers.IntegerField(allow_null=True)
    match_score = serializers.IntegerField()


class TastingResultSerializer(serializers.Serializer):
    tasting_id = serializers.UUIDField()
    title = serializers.CharField()
    result_description = serializers.CharField(allow_null=True)
    podium = TastingResultPodiumItemSerializer(many=True)
    favorites = TastingResultFavoriteItemSerializer(many=True)
    criteria_breakdown = TastingResultCriteriaItemSerializer(many=True)
    top_tags = TastingResultTopTagItemSerializer(many=True)
    tea_matches = TastingResultTeaMatchSerializer(many=True)


class NominateWriteSerializer(serializers.Serializer):
    is_nominated = serializers.BooleanField(default=True)


class NominateResponseSerializer(serializers.Serializer):
    is_nominated = serializers.BooleanField()
    podium_place = serializers.IntegerField(allow_null=True)


class PodiumPatchSerializer(serializers.Serializer):
    first = serializers.UUIDField(required=False, allow_null=True)
    second = serializers.UUIDField(required=False, allow_null=True)
    third = serializers.UUIDField(required=False, allow_null=True)

    def validate(self, attrs):
        non_null = [v for v in attrs.values() if v is not None]
        if len(non_null) != len(set(non_null)):
            raise serializers.ValidationError("Same product cannot occupy multiple podium places.")
        return attrs


class PodiumSnapshotSerializer(serializers.Serializer):
    first = serializers.UUIDField(allow_null=True)
    second = serializers.UUIDField(allow_null=True)
    third = serializers.UUIDField(allow_null=True)
