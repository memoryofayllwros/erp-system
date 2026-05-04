"""
Intent Manager for Chatbot Service

This module defines all valid intents for different user roles in the chatbot system.
Intents are organized by functionality and user permissions.
"""

from typing import FrozenSet

# =============================================================================
# BASE INTENT CATEGORIES
# =============================================================================

# Simple read intents (basic data access)
SIMPLE_READ_INTENTS: FrozenSet[str] = frozenset({
    "read_all_attendance_records",
    "read_all_workers", 
    "today_attendance_situation",
    "read_my_leave_records"
})

# Worker-specific intents (attendance related)
WORKER_VALID_INTENTS: FrozenSet[str] = frozenset({
    "check_in_via_gps",
    "check_in_via_image",
    'leave_application',
    'add_medical_certificate_for_sick_leave',
    'read_my_leave_records',
    'lunch_overtime',
})

# Creation intents
CREATION_INTENTS: FrozenSet[str] = frozenset({
    "add_project",
    "worker_upload_cards"
})

# =============================================================================
# ROLE-BASED INTENT PERMISSIONS
# =============================================================================

# Manager permissions: All worker permissions + project management + read intents
MANAGER_VALID_INTENTS: FrozenSet[str] = frozenset({
    "read_all_attendance_records",
    "read_all_workers",
    "add_project",
    "update_project",
    "delete_project",
    "read_specific_project",
    "add_project_gps",
    "remove_project_gps_location",
    "today_attendance_situation",
    "monthly_payslip",
}) | WORKER_VALID_INTENTS

# Admin permissions: Same as manager permissions
ADMIN_VALID_INTENTS: FrozenSet[str] = frozenset({
    "read_all_attendance_records",
    "read_all_workers",
    "add_project",
    "update_project",
    "delete_project",
    "read_specific_project",
    "add_project_gps",
    "remove_project_gps_location",
    "today_attendance_situation",
    "monthly_payslip",
}) | WORKER_VALID_INTENTS

# =============================================================================
# CONVENIENCE COLLECTIONS
# =============================================================================

# All valid intents across all roles
VALID_INTENTS: FrozenSet[str] = MANAGER_VALID_INTENTS | WORKER_VALID_INTENTS | ADMIN_VALID_INTENTS