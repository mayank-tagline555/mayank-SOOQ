## Setup Steps

    1. Clone the Project:

        git clone git@gitlab.taglineinfotech.com:sooq-althahab/sooq-althahab-be.git
        cd sooq-althahab-be

    2. Create a python environment:

        pip install virtualenv
        python3 -m venv venv

    3. Activate the virtual environment:

        source venv/bin/activate

    4. Install the dependencies:

        pip3 install -r requirements.txt

    5. Install Docker dependencies: (optional)

        docker-compose up -d --build

    6. Migrate database migrations:

        python manage.py migrate

    7. Create Organization:

        python manage.py create_organization

    8. Create Continents/Regions:

        python manage.py create_continent

    9. Create Superuser for admin panel access:

        python manage.py createsuperuser (Note: pass organization code)

    10. Create Global metal: (Note: Do not run this command before creating the super admin.)

        python manage.py create_globalmetal

    11. Create django.po file for integrating new language in our project:
        (Run this command when you want to generate translation files for a specific new language in this project.)

        django-admin makemessages -l <language_code>

    12. Compile messages for multiple language:
        (After making or updating translations in the django.po files, this command compiles them into .mo files, which are binary files required for Django to use the translations at runtime. Without this step, the translations will not take effect in your application.)
        **Note:**
        (The API uses the `Accept-Language` key in the request header to determine the translations. Ensure this key is included in the API requests to serve the appropriate language.)

        django-admin compilemessages

    13. Run python(Django) server:

        python manage.py runserver

    14. Run Celery worker:

        celery -A sooq_althahab worker --loglevel=info

    15. Run Celery beat:

        celery -A sooq_althahab beat --loglevel=info

    16. Generate an Arabic translation Excel file

        python manage.py export_translations
# mayank-SOOQ
