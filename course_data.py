# course_data.py
# DCU Course and Faculty Data
# This file contains all the course information for the DCU timetable system

# Hierarchical course structure: Faculty → Course → Year → Course Details
FACULTIES = {
    "engineering": {
        "name": "Faculty of Engineering & Computing",
        "courses": {
            "COMBUS": {
                "name": "Computing for Business",
                "years": {
                    1: {
                        "id": "dd8e91b3-3f17-8f47-d3aa-c8d62738a1e0",
                        "name": "Computing for Business (Year 1)",
                        "code": "COMBUS1"
                    },
                    2: {
                        "id": "af375a3e-003d-fab5-0a87-88a4b0bde60a",
                        "name": "Computing for Business (Year 2)",
                        "code": "COMBUS2"
                    }
                }
            }
        }
    },
    
    "business": {
        "name": "Faculty of Business",
        "courses": {
            "BS": {
                "name": "Business Studies",
                "years": {
                    1: {
                        "id": "c7599448-d85e-6360-69ec-a584e177b6f1",
                        "name": "Business Studies (Year 1)",
                        "code": "BS1"
                    }
                }
            }
        }
    },
    
    # Template for adding new faculties:
    # "engineering": {
    #     "name": "Faculty of Engineering and Computing",
    #     "courses": {
    #         "COSC": {
    #             "name": "Bachelor of Science in Computer Science",
    #             "years": {
    #                 1: {
    #                     "id": "COURSE_ID_HERE",
    #                     "name": "Bachelor of Science in Computer Science (Year 1)",
    #                     "code": "COSC1"
    #                 },
    #                 2: {
    #                     "id": "COURSE_ID_HERE",
    #                     "name": "Bachelor of Science in Computer Science (Year 2)", 
    #                     "code": "COSC2"
    #                 }
    #             }
    #         }
    #     }
    # }
}

# Helper function to validate the data structure
def validate_course_data():
    """Validate that all course data is properly structured"""
    errors = []
    
    for faculty_key, faculty_data in FACULTIES.items():
        if not isinstance(faculty_data, dict):
            errors.append(f"Faculty '{faculty_key}' must be a dictionary")
            continue
            
        if "name" not in faculty_data:
            errors.append(f"Faculty '{faculty_key}' missing 'name' field")
            
        if "courses" not in faculty_data:
            errors.append(f"Faculty '{faculty_key}' missing 'courses' field")
            continue
            
        for course_key, course_data in faculty_data["courses"].items():
            if not isinstance(course_data, dict):
                errors.append(f"Course '{course_key}' in faculty '{faculty_key}' must be a dictionary")
                continue
                
            if "name" not in course_data:
                errors.append(f"Course '{course_key}' in faculty '{faculty_key}' missing 'name' field")
                
            if "years" not in course_data:
                errors.append(f"Course '{course_key}' in faculty '{faculty_key}' missing 'years' field")
                continue
                
            for year, year_data in course_data["years"].items():
                if not isinstance(year_data, dict):
                    errors.append(f"Year {year} in course '{course_key}' must be a dictionary")
                    continue
                    
                required_fields = ["id", "name", "code"]
                for field in required_fields:
                    if field not in year_data:
                        errors.append(f"Year {year} in course '{course_key}' missing '{field}' field")
    
    return errors

# Helper functions for easy course management
def add_faculty(faculty_key: str, faculty_name: str):
    """Add a new faculty"""
    if faculty_key not in FACULTIES:
        FACULTIES[faculty_key] = {
            "name": faculty_name,
            "courses": {}
        }
        return True
    return False

def add_course_to_faculty(faculty_key: str, course_key: str, course_name: str):
    """Add a new course to an existing faculty"""
    if faculty_key in FACULTIES:
        FACULTIES[faculty_key]["courses"][course_key] = {
            "name": course_name,
            "years": {}
        }
        return True
    return False

def add_year_to_course(faculty_key: str, course_key: str, year: int, course_id: str, full_name: str, code: str):
    """Add a year to an existing course"""
    if (faculty_key in FACULTIES and 
        course_key in FACULTIES[faculty_key]["courses"]):
        
        FACULTIES[faculty_key]["courses"][course_key]["years"][year] = {
            "id": course_id,
            "name": full_name,
            "code": code
        }
        return True
    return False

# Statistics and utility functions
def get_total_courses():
    """Get total number of course codes available"""
    total = 0
    for faculty_data in FACULTIES.values():
        for course_data in faculty_data["courses"].values():
            total += len(course_data["years"])
    return total

def get_all_course_codes():
    """Get a list of all available course codes"""
    codes = []
    for faculty_data in FACULTIES.values():
        for course_data in faculty_data["courses"].values():
            for year_data in course_data["years"].values():
                codes.append(year_data["code"])
    return sorted(codes)

def find_course_by_code(code: str):
    """Find course details by course code"""
    for faculty_key, faculty_data in FACULTIES.items():
        for course_key, course_data in faculty_data["courses"].items():
            for year, year_data in course_data["years"].items():
                if year_data["code"] == code:
                    return {
                        "faculty_key": faculty_key,
                        "faculty_name": faculty_data["name"],
                        "course_key": course_key,
                        "course_name": course_data["name"],
                        "year": year,
                        **year_data
                    }
    return None

# Validate data on import
_validation_errors = validate_course_data()
if _validation_errors:
    import logging
    logger = logging.getLogger("alfred.course_data")
    logger.error(f"Course data validation failed: {_validation_errors}")
    raise ValueError(f"Invalid course data structure: {_validation_errors}")

# Example of how to add new courses (for documentation):
"""
To add a new course:

1. Add a new faculty (if needed):
   add_faculty("engineering", "Faculty of Engineering and Computing")

2. Add a course to the faculty:
   add_course_to_faculty("engineering", "COSC", "Bachelor of Science in Computer Science")

3. Add years to the course:
   add_year_to_course("engineering", "COSC", 1, "course-id-here", "Bachelor of Science in Computer Science (Year 1)", "COSC1")
   add_year_to_course("engineering", "COSC", 2, "course-id-here", "Bachelor of Science in Computer Science (Year 2)", "COSC2")

Or manually edit the FACULTIES dict above.
"""