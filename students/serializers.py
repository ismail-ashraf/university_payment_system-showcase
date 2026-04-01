from rest_framework import serializers
from .models import Student
from payments.models import Payment

class StudentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = [
            'student_id',
            'name',
            'gpa',
            'allowed_hours',
            'status',
            'faculty',
            'national_id',
            'created_at',
            'updated_at',
        ]
        read_only_fields = ['created_at', 'updated_at']
        extra_kwargs = {
            "national_id": {"write_only": True, "required": True},
        }

    def validate_student_id(self, value: str) -> str:
        cleaned = (value or "").strip().upper()
        if not cleaned:
            raise serializers.ValidationError("student_id cannot be blank.")
        return cleaned

    def validate_national_id(self, value: str) -> str:
        cleaned = ''.join([c for c in (value or "") if c.isdigit()])
        if len(cleaned) != 14:
            raise serializers.ValidationError("National ID must be exactly 14 digits.")
        return cleaned

    def validate(self, attrs):
        gpa = attrs.get("gpa")
        allowed_hours = attrs.get("allowed_hours")
        if gpa is not None and allowed_hours is not None:
            if gpa < 2.0 and allowed_hours > 15:
                raise serializers.ValidationError(
                    {"allowed_hours": "GPA below 2.0 limits allowed_hours to 15."}
                )
        return attrs

    def create(self, validated_data):
        if "student_id" in validated_data:
            validated_data["student_id"] = validated_data["student_id"].upper()
        return super().create(validated_data)

    def update(self, instance, validated_data):
        if "student_id" in validated_data:
            validated_data["student_id"] = validated_data["student_id"].upper()
        return super().update(instance, validated_data)


class StudentPaymentDetailSerializer(serializers.ModelSerializer):
    """
    Student-safe payment detail serializer (no audit logs or raw payloads).
    """
    transaction_id = serializers.UUIDField(read_only=True)

    class Meta:
        model = Payment
        fields = [
            "transaction_id",
            "amount",
            "status",
            "payment_method",
            "semester",
            "gateway_reference",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields
