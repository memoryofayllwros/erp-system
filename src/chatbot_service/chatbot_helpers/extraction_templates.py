EXTRACTION_TEMPLATES = {
    "add_project": {
        "required_fields": [
            "project_title",
            "client_name",
            "region",
            "district",
            "street",
        ],
        "optional_fields": ["building", "pic_name"],
    },
    "add_project_gps": {
        "required_fields": ["project_code", "location_name", "latitude", "longitude"]
    },
    "monthly_payslip": {"required_fields": ["year", "month"]},
    "registration": {
        "required_fields": [
            "card_name",
            "english_name",
            "chinese_name",
            "national_id_no",
            "dob",
            "gender",
            "card_image",
        ]
    },
    "lunch_overtime": {"required_fields": ["lunch_ot_date"]},

    "add_project_location_gps": {
        "required_fields": ["project_code", "latitude", "longitude"]
    },
    "add_unprocessed_cards": {"required_fields": ["card_images"]},
    "worker_upload_cards": {"required_fields": ["cards_data"]},
    "worker_sign_in": {"required_fields": ["mobile", "cards_data"]},
    "check_in_via_gps": {
        "required_fields": [
            "project_code",
            "project_id",
            "lat",
            "lon",
            "accuracy",
            "timestamp",
        ]
    },
    "check_in_via_image": {"required_fields": ["image_urls"]},  # list of image urls
    "read_specific_project": {"required_fields": ["project_code"]},
    "remove_project_gps_location": {
        "required_fields": ["project_code", "location_name"]
    },
    "add_reminder": {
        "required_fields": [
            "project_code",
            "reminder_description",
            "reminder_date",
            "reminder_time",
        ]
    },

    "leave_application": {
        "required_fields": [
            "start_date",
            "end_date",
            "is_half_day",
            "leave_type",
        ],
        "optional_fields": ["is_upper_half_day", # bool # True for upper half day, False for lower half day
                            "leave_reason",
                            "project_code", 
                            "medical_certificate"
                            ]
    },
    
    "alternative_registration": {
        "required_fields": [
            "occupation",
            "card_name",
            "country_code",
            "mobile",
            "english_name",
            "chinese_name",
            "national_id_no",
            "dob",
            "gender",
            "national_id_image",
        ]
    },
}
