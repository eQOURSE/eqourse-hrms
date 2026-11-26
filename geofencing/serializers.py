from rest_framework import serializers

from .models import GeoFencing


class GeoFencingSetupSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoFencing
        fields = "__all__"
        read_only_fields = ["formatted_address", "google_place_id"]


class EmployeeLocationSerializer(serializers.ModelSerializer):
    class Meta:
        model = GeoFencing
        fields = ["latitude", "longitude"]
