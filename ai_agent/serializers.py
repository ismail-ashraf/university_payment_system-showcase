from rest_framework import serializers


class AgentQuerySerializer(serializers.Serializer):
    operation = serializers.CharField()
    params = serializers.JSONField(required=False, default=dict)
