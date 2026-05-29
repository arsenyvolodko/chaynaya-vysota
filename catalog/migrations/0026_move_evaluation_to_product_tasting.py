from collections import defaultdict

from django.db import migrations


def forwards(apps, schema_editor):
    """Переносим конфиг оценки и сами отзывы с уровня Product/Tasting на уровень ProductTasting.

    1. ProductTasteCriteria(product, …)      → ProductTastingTasteCriteria для КАЖДОГО ProductTasting этого продукта.
    2. TastingTasteBlock(tasting, …)         → ProductTastingTasteBlock для КАЖДОГО ProductTasting этой дегустации.
    3. ProductReview(user, product)          → «размножаем» по всем ProductTasting продукта:
       первый ProductTasting переиспользует существующую строку (вместе с её ProductCriteriaReview/тегами),
       для остальных создаём клоны с копией оценок и тегов. Отзывы для продуктов вне дегустаций удаляются
       (для них нет per-tasting контейнера).
    """
    ProductTasting = apps.get_model("catalog", "ProductTasting")
    ProductTasteCriteria = apps.get_model("catalog", "ProductTasteCriteria")
    PTTC = apps.get_model("catalog", "ProductTastingTasteCriteria")
    TastingTasteBlock = apps.get_model("catalog", "TastingTasteBlock")
    PTTB = apps.get_model("catalog", "ProductTastingTasteBlock")
    ProductReview = apps.get_model("catalog", "ProductReview")
    ProductCriteriaReview = apps.get_model("catalog", "ProductCriteriaReview")

    pts_by_product = defaultdict(list)
    pts_by_tasting = defaultdict(list)
    for pt in ProductTasting.objects.all():
        pts_by_product[pt.product_id].append(pt)
        pts_by_tasting[pt.tasting_id].append(pt)

    # 1. Критерии: продукт → все его ProductTasting.
    new_ptc = [
        PTTC(
            product_tasting=pt,
            criteria_id=ptc.criteria_id,
            order=ptc.order,
            for_tea_combination=ptc.for_tea_combination,
        )
        for ptc in ProductTasteCriteria.objects.all()
        for pt in pts_by_product.get(ptc.product_id, [])
    ]
    PTTC.objects.bulk_create(new_ptc)

    # 2. Блоки: дегустация → все её ProductTasting.
    new_ptb = [
        PTTB(product_tasting=pt, taste_block_id=ttb.taste_block_id, order=ttb.order)
        for ttb in TastingTasteBlock.objects.all()
        for pt in pts_by_tasting.get(ttb.tasting_id, [])
    ]
    PTTB.objects.bulk_create(new_ptb)

    # 3. Отзывы: размножаем по ProductTasting продукта.
    for rev in list(ProductReview.objects.all()):
        pts = pts_by_product.get(rev.product_id, [])
        if not pts:
            rev.delete()  # продукт не входит ни в одну дегустацию — некуда привязать
            continue

        first, *rest = pts
        rev.product_tasting_id = first.id
        rev.save(update_fields=["product_tasting"])

        if not rest:
            continue

        crs = list(ProductCriteriaReview.objects.filter(product_review_id=rev.id))
        tag_ids = list(rev.taste_tags.values_list("id", flat=True))
        for pt in rest:
            clone = ProductReview.objects.create(
                user_id=rev.user_id,
                product_id=rev.product_id,
                product_tasting_id=pt.id,
                global_comment=rev.global_comment,
                self_comment=rev.self_comment,
                tasted=rev.tasted,
                is_bookmarked=rev.is_bookmarked,
                composition=rev.composition,
            )
            if tag_ids:
                clone.taste_tags.set(tag_ids)
            if crs:
                ProductCriteriaReview.objects.bulk_create(
                    [
                        ProductCriteriaReview(
                            product_review_id=clone.id,
                            criteria_id=cr.criteria_id,
                            mark=cr.mark,
                            x=cr.x,
                        )
                        for cr in crs
                    ]
                )


def backwards(apps, schema_editor):
    # Необратимо без потерь (схлопывание per-tasting отзывов обратно к одному per-product — неоднозначно).
    # Оставляем no-op: откат схемы вернёт старые таблицы пустыми, ручное восстановление данных не предполагается.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0025_productreview_product_tasting_and_more"),
    ]

    operations = [
        # Снимаем старый unique (user, product) ДО fan-out: размножение отзыва по нескольким
        # ProductTasting одного продукта создаёт несколько строк с одинаковым (user, product).
        # Новый unique (user, product_tasting) навешивается в 0027 уже после переноса данных.
        migrations.RemoveConstraint(
            model_name="productreview",
            name="uniq_user_product_review",
        ),
        migrations.RunPython(forwards, backwards),
    ]
