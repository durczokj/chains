from rest_framework import serializers

from lifecycles.models import (
    Generation,
    GenerationLink,
    ProductFamily,
)


class GenerationLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = GenerationLink
        fields = ["predecessor", "successor"]


class GenerationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Generation
        fields = [
            "id", "iso_country_code", "code",
            "start_date", "end_date", "source_transition",
        ]


class ProductFamilySerializer(serializers.ModelSerializer):
    generations = GenerationSerializer(many=True, read_only=True)
    links = serializers.SerializerMethodField()
    code_type_id = serializers.CharField()

    class Meta:
        model = ProductFamily
        fields = ["id", "identifier", "iso_country_code", "code_type_id", "generations", "links"]

    def get_links(self, obj):
        links = GenerationLink.objects.filter(
            predecessor__product_family=obj, successor__product_family=obj
        )
        return GenerationLinkSerializer(links, many=True).data


class ProductFamilyListSerializer(serializers.ModelSerializer):
    generation_count = serializers.IntegerField(source="generations.count", read_only=True)
    code_type_id = serializers.CharField()

    class Meta:
        model = ProductFamily
        fields = ["id", "identifier", "iso_country_code", "code_type_id", "generation_count"]


class CodeResolveSerializer(serializers.Serializer):
    code = serializers.IntegerField()
    code_type = serializers.CharField(max_length=10)
    country = serializers.CharField(max_length=2)
    date = serializers.DateField()


class BulkResolveSerializer(serializers.Serializer):
    queries = CodeResolveSerializer(many=True)
