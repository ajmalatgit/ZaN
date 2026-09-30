from django.db import migrations


def backfill_sellers(apps, schema_editor):
    OrderItem = apps.get_model('core_app', 'OrderItem')
    database = schema_editor.connection.alias
    items = (
        OrderItem.objects.using(database)
        .filter(seller__isnull=True, product__seller__isnull=False)
        .values_list('pk', 'product__seller_id')
        .iterator()
    )
    for item_id, seller_id in items:
        OrderItem.objects.using(database).filter(pk=item_id).update(seller_id=seller_id)


class Migration(migrations.Migration):

    dependencies = [
        ('core_app', '0007_orderitem_fulfillment_status_orderitem_seller_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill_sellers, migrations.RunPython.noop),
    ]
