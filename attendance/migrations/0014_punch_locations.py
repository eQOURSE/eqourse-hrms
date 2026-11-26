from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("attendance", "0013_alter_attendanceconflictresolution_resolution")]

    operations = [
        migrations.AddField(
            model_name=model_name,
            name=name,
            field=field,
        )
        for model_name in (
            "attendance",
            "attendanceactivity",
            "historicalattendance",
            "historicalattendanceactivity",
        )
        for name, field in (
            ("clock_in_latitude", models.FloatField(blank=True, null=True)),
            ("clock_in_longitude", models.FloatField(blank=True, null=True)),
            ("clock_in_accuracy", models.FloatField(blank=True, null=True)),
            ("clock_in_location_at", models.DateTimeField(blank=True, null=True)),
            ("clock_in_location_address", models.CharField(blank=True, max_length=512)),
            ("clock_out_latitude", models.FloatField(blank=True, null=True)),
            ("clock_out_longitude", models.FloatField(blank=True, null=True)),
            ("clock_out_accuracy", models.FloatField(blank=True, null=True)),
            ("clock_out_location_at", models.DateTimeField(blank=True, null=True)),
            ("clock_out_location_address", models.CharField(blank=True, max_length=512)),
        )
    ]
