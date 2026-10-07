from pathlib import Path
from rest_framework import serializers
from .models import Bid

class BidSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bid
        fields = ["id", "title", "bid_number", "source", "source_pdf", "status", "extracted_text", "extracted_metadata", "processing_error", "created_at", "updated_at"]
        read_only_fields = ["status", "extracted_metadata", "processing_error", "created_at", "updated_at"]

    def validate_source_pdf(self, file):
        if Path(file.name).suffix.lower() != ".pdf":
            raise serializers.ValidationError("Upload a PDF file.")
        if file.size > 50 * 1024 * 1024:
            raise serializers.ValidationError("PDF files must be 50 MB or smaller.")
        if file.content_type not in ("application/pdf", "application/octet-stream"):
            raise serializers.ValidationError("The uploaded file must be a PDF.")
        header = file.read(5)
        file.seek(0)
        if header != b"%PDF-":
            raise serializers.ValidationError("The file does not have a valid PDF header.")
        return file
