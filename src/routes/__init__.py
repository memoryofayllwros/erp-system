"""
API Routes Configuration
"""

from fastapi import APIRouter

from src.routes import (attendance_via_gps_routes, attendance_via_image_routes,
                        card_summary_routes, client_company_routes, employee_contract_routes,
                        nearby_projects_routes, project_routes,
                        redis_monitor_routes, shift_config_routes, user_routes, 
                        worker_routes,
                        leave_routes)

api_router = APIRouter()

# Project routes
api_router.include_router(project_routes.router, tags=["Project"])

# User routes
api_router.include_router(user_routes.router, tags=["User"])

# Worker routes
api_router.include_router(worker_routes.router, tags=["Worker"])


# Employee contract routes
api_router.include_router(employee_contract_routes.router, tags=["Employee contract"])


# Redis and Temporal monitoring routes
api_router.include_router(
    redis_monitor_routes.router, tags=["Redis and Temporal monitoring"]
)

# Check-in routes
# api_router.include_router(attendance_routes.router, tags=["Check-in"])
api_router.include_router(attendance_via_gps_routes.router, tags=["GPS Check-in"])
api_router.include_router(attendance_via_image_routes.router, tags=["Image Check-in"])

# Card summary routes
api_router.include_router(card_summary_routes.router, tags=["Card summary"])

# Nearby projects routes
api_router.include_router(nearby_projects_routes.router, tags=["Nearby Projects"])

# Shift configuration routes
api_router.include_router(shift_config_routes.router, tags=["Shift Configuration"])

# Client company routes
api_router.include_router(client_company_routes.router, tags=["Client Company"])

# Leave routes
api_router.include_router(leave_routes.router, tags=["Leave"])