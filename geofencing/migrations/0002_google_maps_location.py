from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("geofencing", "0001_initial")]

    operations = [
        migrations.AddField(
            model_name="geofencing",
            name="formatted_address",
            field=models.CharField(blank=True, max_length=512),
        ),
        migrations.AddField(
            model_name="geofencing",
            name="google_place_id",
            field=models.CharField(blank=True, max_length=255),
        ),
    ]
