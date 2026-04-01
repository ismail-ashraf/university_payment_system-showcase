"""
scripts/seed_data.py
Phase 2 — Seeds 50 dummy students AND one pending Payment per active student.

Usage:
    python scripts/seed_data.py

Run AFTER: python manage.py migrate
"""

import os
import sys
import random
import django
from decimal import Decimal

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from students.models import Student
from students.fee_calculator import calculate_student_fees
from payments.models import Payment, PaymentAuditLog, current_semester

# ── Config ────────────────────────────────────────────────────────────────────
FACULTIES = ["Engineering", "Science", "Commerce", "Medicine", "Law", "Arts"]
STATUSES  = ["active", "active", "active", "inactive", "suspended"]

ARABIC_NAMES = [
    "Ahmed Hassan", "Mohamed Ali", "Sara Ibrahim", "Fatima Nour",
    "Omar Khalid", "Layla Mostafa", "Youssef Samir", "Nada Tarek",
    "Amr Essam", "Hana Khaled", "Kareem Fathy", "Dina Wael",
    "Mahmoud Rashed", "Aya Magdy", "Tamer Sayed", "Rania Adel",
    "Amir Zakaria", "Mona Sherif", "Hassan Nabil", "Noura Hamdi",
    "Khaled Ramadan", "Salma Gamal", "Ibrahim Lotfy", "Mariam Fouad",
    "Sherif Bahaa", "Yasmine Atef", "Walid Emad", "Heba Saeed",
    "Mostafa Kamal", "Reem Alaa", "Tarek Mansour", "Dalia Fares",
    "Sameh Younis", "Rana Hesham", "Adel Moustafa", "Ghada Refaat",
    "Wael Sobhy", "Nour Sherif", "Bassem Osama", "Zeinab Mohsen",
    "Fady Hanna", "Miral Raafat", "George Farid", "Christine Adly",
    "Bishoy Naguib", "Mary Emile", "Andrew Samir", "Sandra Magdy",
    "Hossam Anwar", "Lobna Kamel",
]

random.seed(42)
SEMESTER = current_semester()


def generate_allowed_hours(gpa: float) -> int:
    if gpa >= 3.0:
        return random.choice([18, 19, 20, 21])
    elif gpa >= 2.0:
        return random.choice([15, 16, 17, 18])
    else:
        return random.choice([12, 13, 14, 15])


# ── Phase 1: Seed students ────────────────────────────────────────────────────

def seed_students() -> list[Student]:
    print("\n" + "=" * 65)
    print("  PHASE 1 — Seeding Students")
    print("=" * 65)
    created_count = skipped_count = 0
    students = []

    for i, name in enumerate(ARABIC_NAMES, start=1):
        student_id  = f"2021{str(i).zfill(4)}"
        gpa         = round(random.uniform(1.40, 4.00), 2)
        allowed_hrs = generate_allowed_hours(gpa)
        faculty     = random.choice(FACULTIES)
        acad_year   = random.randint(1, 5)
        status_val  = random.choice(STATUSES)
        email       = f"{name.lower().replace(' ', '.')}@university.edu.eg"

        student, created = Student.objects.get_or_create(
            student_id=student_id,
            defaults={
                "name":           name,
                "email":          email,
                "faculty":        faculty,
                "academic_year":  acad_year,
                "gpa":            gpa,
                "allowed_hours":  allowed_hrs,
                "registered_hours": 0,
                "status":         status_val,
            },
        )
        students.append(student)

        if created:
            created_count += 1
            tag = "✅ Created "
        else:
            skipped_count += 1
            tag = "⏭️  Skipped "

        print(
            f"  {tag} {student_id} | {name:<22} | {student.faculty:<12} "
            f"| GPA {student.gpa} | {student.allowed_hours} hrs | {student.status}"
        )

    print(f"\n  Students → {created_count} created, {skipped_count} skipped.")
    return students


# ── Phase 2: Seed payments ────────────────────────────────────────────────────

def seed_payments(students: list[Student]) -> None:
    print("\n" + "=" * 65)
    print(f"  PHASE 2 — Seeding Payments  (semester: {SEMESTER})")
    print("=" * 65)
    created_count = skipped_count = 0

    for student in students:
        # Only active students get a pending payment
        if student.status != "active":
            print(f"  ⏩  Skipped  {student.student_id} ({student.status} — no payment created)")
            skipped_count += 1
            continue

        # Idempotent: skip if a PENDING payment already exists this semester
        already_exists = Payment.objects.filter(
            student=student,
            semester=SEMESTER,
            status=Payment.PaymentStatus.PENDING,
        ).exists()

        if already_exists:
            print(f"  ⏭️  Skipped  {student.student_id} (payment already exists for {SEMESTER})")
            skipped_count += 1
            continue

        # Compute expected fee
        breakdown = calculate_student_fees(allowed_hours=student.allowed_hours)
        amount    = Decimal(str(breakdown.total))

        payment = Payment.objects.create(
            student=student,
            amount=amount,
            semester=SEMESTER,
            status=Payment.PaymentStatus.PENDING,
            used=False,
        )
        PaymentAuditLog.objects.create(
            payment=payment,
            event_type=PaymentAuditLog.EventType.INITIATED,
            amount=amount,
            actor="seed_script",
            payload={
                "student_id":    student.student_id,
                "allowed_hours": student.allowed_hours,
                "gpa":           str(student.gpa),
                "source":        "seed_data.py",
            },
        )

        created_count += 1
        print(
            f"  ✅  Payment  {student.student_id} | {student.name:<22} "
            f"| {amount} EGP | txn: {str(payment.transaction_id)[:8]}…"
        )

    print(f"\n  Payments → {created_count} created, {skipped_count} skipped.")


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n🌱 University Smart Payment System — Seed Script")
    students = seed_students()
    seed_payments(students)
    print("\n" + "=" * 65)
    print("  ✅ Seed complete.")
    print("=" * 65 + "\n")