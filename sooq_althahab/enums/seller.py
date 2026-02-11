from django.db import models
from django.db.models import TextChoices


class PremiumValueType(TextChoices):
    PERCENTAGE = "PERCENTAGE", "Percentage"
    AMOUNT = "AMOUNT", "Amount"
    BOTH = "BOTH", "Both"


class CertificateType(TextChoices):
    GIA = "GIA", "GIA"
    IGI = "IGI", "IGI"
    DANAT = "DANAT", "Danat"
    NOT_CERTIFIED = "NOT_CERTIFIED", "Not Certified"


class CommonGradeType(TextChoices):
    EXCELLENT = "EXCELLENT", "Excellent"
    VERY_GOOD = "VERY_GOOD", "Very Good"
    GOOD = "GOOD", "Good"
    FAIR = "FAIR", "Fair"
    POOR = "POOR", "Poor"


class FluorescenceGradeType(TextChoices):
    NONE = "NONE", "None"
    FAINT = "FAINT", "Faint"
    MEDIUM = "MEDIUM", "Medium"
    STRONG = "STRONG", "Strong"
    VERY_STRONG = "VERY_STRONG", "Very Strong"


class ClarityGradeType(TextChoices):
    FL = "FL", "Flawless"
    IF = "IF", "Internally Flawless"
    VVS1 = "VVS1", "Very, Very Slightly Included (VVS1)"
    VVS2 = "VVS2", "Very, Very Slightly Included (VVS2)"
    VS1 = "VS1", "Very Slightly Included (VS1)"
    VS2 = "VS2", "Very Slightly Included (VS2)"
    SI1 = "SI1", "Slightly Included (SI1)"
    SI2 = "SI2", "Slightly Included (SI2)"
    I1 = "I1", "Included (I1) - Visible Flaws"
    I3 = "I3", "Included (I3) - Visible Flaws"
