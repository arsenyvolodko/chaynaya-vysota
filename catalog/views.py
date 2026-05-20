from collections import defaultdict
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Count, Prefetch
from drf_spectacular.utils import OpenApiParameter, extend_schema, extend_schema_view
from rest_framework import status
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import GenericViewSet, ReadOnlyModelViewSet

from .models import (
    Config,
    TasteTags,
    Product,
    ProductCriteriaReview,
    ProductIceCreamLogo,
    ProductReview,
    ProductTasteCriteria,
    ProductTasting,
    ProductTastingUserMark,
    ProductTypeEnum,
    TasteCriteria,
    Tasting,
    TastingParticipation,
)
from .serializers import (
    ConfigSerializer,
    NominateResponseSerializer,
    NominateWriteSerializer,
    PodiumPatchSerializer,
    PodiumSnapshotSerializer,
    ProductInTastingSerializer,
    ProductReviewWriteSerializer,
    ProductSerializer,
    TastingDetailSerializer,
    TastingListSerializer,
    TastingParticipationSerializer,
    TastingResultSerializer,
)


def _user_reviews_prefetch(user):
    if user.is_authenticated:
        qs = ProductReview.objects.filter(user=user).prefetch_related("criteria_reviews", "taste_tags")
    else:
        qs = ProductReview.objects.none()
    return Prefetch("reviews", queryset=qs, to_attr="_user_reviews")


def _user_marks_prefetch(user):
    if user.is_authenticated:
        marks_qs = ProductTastingUserMark.objects.filter(user=user)
    else:
        marks_qs = ProductTastingUserMark.objects.none()
    pt_qs = ProductTasting.objects.select_related("tasting").prefetch_related(
        Prefetch("user_marks", queryset=marks_qs, to_attr="_user_marks_list")
    )
    return Prefetch("producttasting_set", queryset=pt_qs, to_attr="_pt_for_marks")


_PRODUCT_RELATED = ("line",)
_PRODUCT_PREFETCH = (
    "logos",
    "taste_tags",
    Prefetch(
        "producttastecriteria_set",
        queryset=ProductTasteCriteria.objects.select_related("criteria", "criteria__chart").order_by("order", "id"),
        to_attr="_taste_criteria_rows",
    ),
)


_TRUTHY = {"true", "1", "yes", "t", "y"}
_FALSY = {"false", "0", "no", "f", "n"}


def _parse_query_bool(value: str | None, *, field: str) -> bool | None:
    if value is None:
        return None
    lowered = value.lower()
    if lowered in _TRUTHY:
        return True
    if lowered in _FALSY:
        return False
    raise ValidationError({field: "Must be a boolean (true/false)."})


@extend_schema_view(
    list=extend_schema(
        parameters=[
            OpenApiParameter(
                name="type",
                description="Filter by product type",
                required=False,
                type=str,
                enum=[choice[0] for choice in ProductTypeEnum.choices],
            ),
            OpenApiParameter(
                name="name",
                description="Case-insensitive substring match on name",
                required=False,
                type=str,
            ),
            OpenApiParameter(
                name="tasted",
                description="Filter by whether the current user has tasted the product. "
                "For anonymous users, `tasted=true` returns an empty list.",
                required=False,
                type=bool,
            ),
            OpenApiParameter(
                name="bookmarked",
                description="Filter by whether the current user has bookmarked the product. "
                "For anonymous users, `bookmarked=true` returns an empty list.",
                required=False,
                type=bool,
            ),
        ]
    )
)
class ProductViewSet(ReadOnlyModelViewSet):
    serializer_class = ProductSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        qs = Product.objects.all().order_by("id").select_related(*_PRODUCT_RELATED).prefetch_related(*_PRODUCT_PREFETCH)
        product_type = self.request.query_params.get("type")
        name = self.request.query_params.get("name")
        tasted = _parse_query_bool(self.request.query_params.get("tasted"), field="tasted")
        bookmarked = _parse_query_bool(self.request.query_params.get("bookmarked"), field="bookmarked")

        if product_type:
            qs = qs.filter(type=product_type)
        if name:
            qs = qs.filter(name__icontains=name)

        user = self.request.user
        if tasted is not None:
            if user.is_authenticated:
                qs = (
                    qs.filter(reviews__user=user, reviews__tasted=True)
                    if tasted
                    else qs.exclude(reviews__user=user, reviews__tasted=True)
                )
            elif tasted:
                qs = qs.none()

        if bookmarked is not None:
            if user.is_authenticated:
                qs = (
                    qs.filter(reviews__user=user, reviews__is_bookmarked=True)
                    if bookmarked
                    else qs.exclude(reviews__user=user, reviews__is_bookmarked=True)
                )
            elif bookmarked:
                qs = qs.none()

        if user.is_authenticated:
            qs = qs.prefetch_related(_user_reviews_prefetch(user), _user_marks_prefetch(user))
        return qs

    @extend_schema(request=ProductReviewWriteSerializer, responses={200: ProductSerializer, 201: ProductSerializer})
    @action(detail=True, methods=["post"], url_path="review", permission_classes=[IsAuthenticated])
    def review(self, request, pk=None):
        product = self.get_object()
        payload = ProductReviewWriteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data

        criteria_marks = data.get("criteria_marks")
        criteria_pairs = self._resolve_criteria_marks(product, criteria_marks) if criteria_marks else []

        tag_ids = data.get("taste_tags")
        resolved_tags = self._resolve_taste_tags(product, tag_ids) if tag_ids is not None else None

        meaningful_keys = {"global_comment", "self_comment", "composition", "criteria_marks", "taste_tags"}
        implies_tasted = bool(meaningful_keys & data.keys())

        with transaction.atomic():
            review, created = ProductReview.objects.get_or_create(user=request.user, product=product)

            for field in ("global_comment", "self_comment", "composition", "tasted", "is_bookmarked"):
                if field in data:
                    setattr(review, field, data[field])
            if implies_tasted and not review.tasted:
                review.tasted = True
            review.save()

            for criteria, mark in criteria_pairs:
                ProductCriteriaReview.objects.update_or_create(
                    product_review=review,
                    criteria=criteria,
                    defaults={"mark": mark},
                )

            if resolved_tags is not None:
                review.taste_tags.set(resolved_tags)

        product.__dict__["_cached_user_review"] = review
        return Response(
            ProductSerializer(product, context={"request": request}).data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @staticmethod
    def _resolve_criteria_marks(product: Product, criteria_marks: dict[str, int]) -> list[tuple[TasteCriteria, int]]:
        try:
            wanted_ids = {int(key): mark for key, mark in criteria_marks.items()}
        except (TypeError, ValueError):
            raise ValidationError({"criteria_marks": "Keys must be integer TasteCriteria ids."})

        linked = {c.pk: c for c in product.taste_criteria.filter(pk__in=wanted_ids.keys())}
        missing = sorted(wanted_ids.keys() - linked.keys())
        if missing:
            raise ValidationError(
                {"criteria_marks": f"Criteria not linked to this product: {missing}."}
            )
        return [(linked[cid], mark) for cid, mark in wanted_ids.items()]

    @staticmethod
    def _resolve_taste_tags(product: Product, tag_ids: list[int]) -> list[TasteTags]:
        wanted = set(tag_ids)
        linked = list(product.taste_tags.filter(pk__in=wanted))
        missing = sorted(wanted - {t.pk for t in linked})
        if missing:
            raise ValidationError(
                {"taste_tags": f"Tags not linked to this product: {missing}."}
            )
        return linked


class TastingViewSet(RetrieveModelMixin, GenericViewSet):

    def get_queryset(self):
        qs = Tasting.objects.all()
        if self.action in ("products", "product_detail"):
            user = self.request.user
            product_qs = Product.objects.select_related(*_PRODUCT_RELATED).prefetch_related(*_PRODUCT_PREFETCH)
            if user.is_authenticated:
                product_qs = product_qs.prefetch_related(_user_reviews_prefetch(user), _user_marks_prefetch(user))
            combo_qs = Product.objects.prefetch_related("logos")
            pt_prefetch = Prefetch(
                "producttasting_set",
                queryset=ProductTasting.objects.prefetch_related(
                    Prefetch("product", queryset=product_qs),
                    Prefetch("tea_flavor_combination", queryset=combo_qs),
                ).order_by("order"),
                to_attr="_pt_rows",
            )
            qs = qs.prefetch_related(pt_prefetch)
        return qs

    def _products_in_tasting(self, tasting: Tasting, user) -> list[Product]:
        rows = getattr(tasting, "_pt_rows", None)
        if rows is None:
            rows = list(
                ProductTasting.objects.filter(tasting=tasting)
                .select_related("product")
                .prefetch_related("tea_flavor_combination")
                .order_by("order")
            )

        marks_by_pid: dict = {}
        if user.is_authenticated:
            marks = ProductTastingUserMark.objects.filter(user=user, tasting=tasting).select_related(
                "product_tasting"
            )
            marks_by_pid = {m.product_tasting.product_id: m for m in marks}

        products: list[Product] = []
        for pt in rows:
            p = pt.product
            p.__dict__["_tea_flavor_combination"] = list(pt.tea_flavor_combination.all())
            p.__dict__["_category"] = pt.category
            p.__dict__["_current_tasting_mark"] = marks_by_pid.get(p.id)
            products.append(p)
        return products

    def get_serializer_class(self):
        if self.action == "join":
            return TastingParticipationSerializer
        if self.action == "my":
            return TastingListSerializer
        return TastingDetailSerializer

    def get_permissions(self):
        if self.action in ("retrieve", "products", "product_detail"):
            return [AllowAny()]
        return [IsAuthenticated()]

    @extend_schema(responses={200: ProductInTastingSerializer(many=True)})
    @action(detail=True, methods=["get"], url_path="products")
    def products(self, request, pk=None):
        tasting = self.get_object()
        products = self._products_in_tasting(tasting, request.user)
        return Response(
            ProductInTastingSerializer(products, many=True, context={"request": request}).data
        )

    @extend_schema(responses={200: ProductInTastingSerializer})
    @action(
        detail=True,
        methods=["get"],
        url_path=r"products/(?P<product_id>[0-9a-fA-F-]+)",
    )
    def product_detail(self, request, pk=None, product_id=None):
        tasting = self.get_object()
        products = self._products_in_tasting(tasting, request.user)
        target = next((p for p in products if str(p.id) == str(product_id)), None)
        if target is None:
            raise NotFound("Product is not part of this tasting.")
        return Response(
            ProductInTastingSerializer(target, context={"request": request}).data
        )

    @extend_schema(request=None, responses={200: TastingParticipationSerializer, 201: TastingParticipationSerializer})
    @action(detail=True, methods=["post"], url_path="join")
    def join(self, request, pk=None):
        tasting = self.get_object()
        with transaction.atomic():
            participation, created = TastingParticipation.objects.get_or_create(
                tasting=tasting,
                user=request.user,
            )
            product_ids = tasting.products.values_list("id", flat=True)
            ProductReview.objects.bulk_create(
                [ProductReview(user=request.user, product_id=pid, tasted=True) for pid in product_ids],
                ignore_conflicts=True,
            )
            ProductReview.objects.filter(
                user=request.user, product_id__in=product_ids, tasted=False,
            ).update(tasted=True)
        serializer = self.get_serializer(participation)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK,
        )

    @extend_schema(responses={200: TastingListSerializer(many=True)})
    @action(detail=False, methods=["get"], url_path="my")
    def my(self, request):
        qs = Tasting.objects.filter(participants=request.user).order_by("-date")
        serializer = self.get_serializer(qs, many=True)
        return Response(serializer.data)

    @extend_schema(request=NominateWriteSerializer, responses={200: NominateResponseSerializer})
    @action(
        detail=True,
        methods=["post"],
        url_path=r"products/(?P<product_id>[0-9a-fA-F-]+)/nominate",
        permission_classes=[IsAuthenticated],
    )
    def nominate(self, request, pk=None, product_id=None):
        tasting = self.get_object()
        product_tasting = ProductTasting.objects.filter(tasting=tasting, product_id=product_id).first()
        if product_tasting is None:
            raise NotFound("Product is not part of this tasting.")

        body = NominateWriteSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        is_nominated = body.validated_data["is_nominated"]

        mark, created = ProductTastingUserMark.objects.get_or_create(
            user=request.user,
            product_tasting=product_tasting,
            defaults={"is_nominated": is_nominated},
        )
        if not created and mark.is_nominated != is_nominated:
            mark.is_nominated = is_nominated
            mark.save(update_fields=["is_nominated", "updated_at"])

        return Response({"is_nominated": mark.is_nominated, "podium_place": mark.podium_place})

    @extend_schema(request=PodiumPatchSerializer, responses={200: PodiumSnapshotSerializer})
    @action(detail=True, methods=["patch"], url_path="podium", permission_classes=[IsAuthenticated])
    def podium(self, request, pk=None):
        tasting = self.get_object()
        body = PodiumPatchSerializer(data=request.data)
        body.is_valid(raise_exception=True)

        place_to_field = {1: "first", 2: "second", 3: "third"}
        field_to_place = {v: k for k, v in place_to_field.items()}

        with transaction.atomic():
            for field, place in field_to_place.items():
                if field not in body.validated_data:
                    continue
                target_product_id = body.validated_data[field]

                ProductTastingUserMark.objects.filter(
                    user=request.user, tasting=tasting, podium_place=place,
                ).update(podium_place=None)

                if target_product_id is None:
                    continue

                pt = ProductTasting.objects.filter(tasting=tasting, product_id=target_product_id).first()
                if pt is None:
                    raise NotFound(f"Product {target_product_id} is not part of this tasting.")

                mark, _ = ProductTastingUserMark.objects.get_or_create(
                    user=request.user,
                    product_tasting=pt,
                )
                mark.podium_place = place
                mark.save(update_fields=["podium_place", "updated_at"])

        snapshot = {"first": None, "second": None, "third": None}
        current = ProductTastingUserMark.objects.filter(
            user=request.user, tasting=tasting, podium_place__isnull=False,
        ).select_related("product_tasting")
        for m in current:
            snapshot[place_to_field[m.podium_place]] = m.product_tasting.product_id
        return Response(snapshot)

    @extend_schema(responses={200: TastingResultSerializer})
    @action(detail=True, methods=["get"], url_path="result", permission_classes=[IsAuthenticated])
    def result(self, request, pk=None):
        tasting = self.get_object()
        participation = TastingParticipation.objects.filter(
            tasting=tasting, user=request.user,
        ).first()
        if participation is None:
            raise NotFound("You have not joined this tasting.")
        return Response(_build_tasting_result(participation, request))


class ResultViewSet(RetrieveModelMixin, GenericViewSet):
    queryset = TastingParticipation.objects.select_related("tasting", "user")
    permission_classes = [AllowAny]
    serializer_class = TastingResultSerializer

    @extend_schema(responses={200: TastingResultSerializer})
    def retrieve(self, request, *args, **kwargs):
        participation = self.get_object()
        return Response(_build_tasting_result(participation, request))


class ConfigView(APIView):
    permission_classes = [AllowAny]

    @extend_schema(responses={200: ConfigSerializer})
    def get(self, request):
        return Response(ConfigSerializer(Config.load()).data)


def _build_tasting_result(participation: TastingParticipation, request) -> dict:
    tasting = participation.tasting
    user = participation.user
    product_ids = list(tasting.products.values_list("id", flat=True))

    podium_marks = list(
        ProductTastingUserMark.objects.filter(
            user=user, tasting=tasting, podium_place__isnull=False,
        )
        .select_related("product_tasting__product")
        .order_by("podium_place")
    )
    favorite_marks = list(
        ProductTastingUserMark.objects.filter(
            user=user, tasting=tasting, is_nominated=True, podium_place__isnull=True,
        ).select_related("product_tasting__product")
    )

    scored_product_ids = [m.product_tasting.product_id for m in podium_marks]
    reviews_by_product = {
        r.product_id: r
        for r in ProductReview.objects.filter(user=user, product_id__in=scored_product_ids)
        .prefetch_related("criteria_reviews", "taste_tags")
    }

    podium = [
        {
            "place": m.podium_place,
            "id": m.product_tasting.product_id,
            "name": m.product_tasting.product.name,
            "number": m.product_tasting.product.number,
            "total_score": _review_total_score(reviews_by_product.get(m.product_tasting.product_id)),
        }
        for m in podium_marks
    ]
    favorites = [
        {
            "id": m.product_tasting.product_id,
            "name": m.product_tasting.product.name,
            "number": m.product_tasting.product.number,
        }
        for m in favorite_marks
    ]

    ptc_rows = (
        ProductTasteCriteria.objects.filter(product_id__in=product_ids)
        .select_related("criteria")
    )
    criteria_obj_by_id: dict[int, TasteCriteria] = {}
    criteria_product_count: dict[int, int] = defaultdict(int)
    for row in ptc_rows:
        criteria_obj_by_id[row.criteria_id] = row.criteria
        criteria_product_count[row.criteria_id] += 1

    user_totals: dict[int, int] = defaultdict(int)
    if criteria_obj_by_id:
        user_mark_rows = ProductCriteriaReview.objects.filter(
            product_review__user=user,
            product_review__product_id__in=product_ids,
            criteria_id__in=criteria_obj_by_id.keys(),
        ).values_list("criteria_id", "mark")
        for cid, mark in user_mark_rows:
            user_totals[cid] += mark

    criteria_breakdown = []
    for criteria in sorted(criteria_obj_by_id.values(), key=lambda c: (c.order, c.id)):
        cid = criteria.id
        grade = criteria.grade or []
        values: list[int] = []
        for item in grade:
            try:
                values.append(int(item["value"]))
            except (KeyError, TypeError, ValueError):
                continue
        count = criteria_product_count[cid]
        min_total = (min(values) * count) if values else 0
        max_total = (max(values) * count) if values else 0
        criteria_breakdown.append({
            "id": cid,
            "name": criteria.name,
            "min_total": min_total,
            "max_total": max_total,
            "user_total": user_totals.get(cid, 0),
        })

    top_tags_qs = (
        TasteTags.objects.filter(
            reviews__user=user,
            reviews__product_id__in=product_ids,
        )
        .annotate(count=Count("reviews", distinct=True))
        .order_by("-count", "id")[:3]
    )
    top_tags = [
        {"id": t.id, "name": t.name, "weight": t.weight, "count": t.count}
        for t in top_tags_qs
    ]

    pt_with_combos = (
        ProductTasting.objects.filter(tasting=tasting)
        .select_related("product")
        .prefetch_related(
            Prefetch("tea_flavor_combination", queryset=Product.objects.prefetch_related("logos")),
        )
    )
    tea_obj_by_id: dict = {}
    tea_to_products: dict = defaultdict(set)
    product_obj_by_id: dict = {}
    for pt in pt_with_combos:
        product_obj_by_id[pt.product_id] = pt.product
        for tea in pt.tea_flavor_combination.all():
            tea_obj_by_id[tea.id] = tea
            tea_to_products[tea.id].add(pt.product_id)

    match_criteria_ids = set(
        ProductTasteCriteria.objects.filter(
            product_id__in=product_ids, for_tea_combination=True,
        ).values_list("criteria_id", flat=True).distinct()
    )
    match_scores: dict = defaultdict(int)
    if match_criteria_ids and tea_to_products:
        match_rows = ProductCriteriaReview.objects.filter(
            product_review__user=user,
            product_review__product_id__in=product_ids,
            criteria_id__in=match_criteria_ids,
        ).values_list("product_review__product_id", "mark")
        for pid, mark in match_rows:
            match_scores[pid] += mark

    tea_matches = []
    for tea_id, paired_pids in tea_to_products.items():
        scored = [(pid, match_scores[pid]) for pid in paired_pids if pid in match_scores]
        if not scored:
            continue
        scored.sort(key=lambda x: (-x[1], str(x[0])))
        top_pid, top_score = scored[0]
        tea = tea_obj_by_id[tea_id]
        top_product = product_obj_by_id[top_pid]
        tea_matches.append({
            "tea_id": tea.id,
            "tea_name": tea.name,
            "tea_logo": _file_url(tea.image, request),
            "product_id": top_product.id,
            "product_name": top_product.name,
            "product_number": top_product.number,
            "match_score": top_score,
        })
    tea_matches.sort(key=lambda x: (x["tea_name"] or "", str(x["tea_id"])))

    ice_cream_stats = _ice_cream_stats(_reviewed_product_ids(user, product_ids), request)

    return {
        "result_id": participation.id,
        "tasting_id": tasting.id,
        "title": tasting.title,
        "type": tasting.type,
        "result_description": tasting.result_description,
        "podium": podium,
        "favorites": favorites,
        "criteria_breakdown": criteria_breakdown,
        "top_tags": top_tags,
        "tea_matches": tea_matches,
        "ice_cream_stats": ice_cream_stats,
    }


def _review_total_score(review: ProductReview | None) -> int | None:
    if review is None:
        return None
    marks_sum = sum(cr.mark for cr in review.criteria_reviews.all())
    weights_sum = sum(t.weight for t in review.taste_tags.all())
    total = Decimal(str(marks_sum + weights_sum))
    return int(total.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _reviewed_product_ids(user, product_ids: list) -> set:
    reviews = (
        ProductReview.objects.filter(user=user, product_id__in=product_ids)
        .prefetch_related("criteria_reviews", "taste_tags")
    )
    reviewed: set = set()
    for r in reviews:
        if (
            r.global_comment
            or r.self_comment
            or r.composition
            or list(r.criteria_reviews.all())
            or list(r.taste_tags.all())
        ):
            reviewed.add(r.product_id)
    return reviewed


def _ice_cream_stats(product_ids, request) -> dict[str, dict[str, dict]]:
    if not product_ids:
        return {}
    rows = (
        ProductIceCreamLogo.objects.filter(product_id__in=product_ids)
        .select_related("logo")
        .order_by("id")
    )

    products_by_bucket: dict[tuple[str, str], set] = defaultdict(set)
    image_by_bucket: dict[tuple[str, str], str | None] = {}
    for row in rows:
        logo = row.logo
        text = logo.text
        if not text:
            continue
        key = (logo.type, text)
        products_by_bucket[key].add(row.product_id)
        if key not in image_by_bucket:
            image_by_bucket[key] = _file_url(logo.image, request)

    stats: dict[str, dict[str, dict]] = defaultdict(dict)
    for (type_, text), pids in products_by_bucket.items():
        stats[type_][text] = {
            "amount": len(pids),
            "image": image_by_bucket.get((type_, text)),
        }
    return stats


def _file_url(file_field, request) -> str | None:
    if not file_field:
        return None
    url = file_field.url
    return request.build_absolute_uri(url) if request is not None else url

