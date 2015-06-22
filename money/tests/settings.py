import os

# Settings to be used when running tests

TEST_DIR = os.path.join(os.path.abspath(os.path.dirname(__file__)))

STATIC_URL = '/static/'

STATIC_ROOT = os.path.join(TEST_DIR, 'static')

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    },
    # 'default': {
    #     'ENGINE': 'django.db.backends.postgresql_psycopg2',
    #     'NAME': 'money',
    # }
}

INSTALLED_APPS = (
    'money',
    'money.tests',
)

SECRET_KEY = 'abcde12345'

ROOT_URLCONF = 'money.tests.urls'

CACHES = {
    # No cache
    'default': {
        'BACKEND': 'django.core.cache.backends.dummy.DummyCache',
    }
}

FIXTURE_DIRS = ('../money/contrib/django/tests/fixtures/',)

PASSWORD_HASHERS = (
    'django.contrib.auth.hashers.UnsaltedMD5PasswordHasher',
)

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'level': 'DEBUG',
            'class': 'logging.StreamHandler'
        },
    },
    'loggers': {
        'django.request': {
            'handlers': ['console'],
            'level': 'INFO',
            'propagate': True,
        },
        'money': {
            'handlers': ['console'],
            'level': 'DEBUG'
        },
    }
}
