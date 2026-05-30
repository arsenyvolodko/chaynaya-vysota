from django.db import migrations


def forwards(apps, schema_editor):
    """Раньше критерии чарта добавлялись в ProductTasting поштучно через ProductTastingTasteCriteria.
    Теперь карточка берёт чарты из M2M ProductTasting.charts. Чтобы ранее настроенные чарты не пропали,
    для каждого (product_tasting, chart), встречающегося среди критериев-через-through, создаём привязку
    ProductTastingChart. Сами through-строки не трогаем (для критериев чарта они становятся инертными)."""
    ProductTastingTasteCriteria = apps.get_model("catalog", "ProductTastingTasteCriteria")
    ProductTastingChart = apps.get_model("catalog", "ProductTastingChart")

    seen: set[tuple[int, int]] = set()
    new_links = []
    rows = ProductTastingTasteCriteria.objects.filter(criteria__chart__isnull=False).values_list(
        "product_tasting_id", "criteria__chart_id", "order"
    )
    for product_tasting_id, chart_id, order in rows:
        key = (product_tasting_id, chart_id)
        if key in seen:
            continue
        seen.add(key)
        new_links.append(ProductTastingChart(product_tasting_id=product_tasting_id, chart_id=chart_id, order=order))
    ProductTastingChart.objects.bulk_create(new_links, ignore_conflicts=True)


def backwards(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0029_producttastingchart_producttasting_charts_and_more"),
    ]

    operations = [
        migrations.RunPython(forwards, backwards),
    ]
