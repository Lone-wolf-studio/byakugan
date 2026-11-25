"""Behavior tests for static Django model and URL analysis."""

from pathlib import Path
import tempfile
import unittest

from byakugan.cli import render_text
from byakugan.django import analyze_django
from byakugan.scan import scan_project


MODELS = (
    "from django.db import models\n"
    "from django.conf import settings\n"
    "class Author(models.Model):\n"
    "    name = models.CharField(max_length=100)\n"
    "class Book(models.Model):\n"
    "    title = models.CharField(max_length=100)\n"
    "    author = models.ForeignKey('Author', on_delete=models.CASCADE)\n"
    "    tags = models.ManyToManyField('Tag')\n"
    "    owner = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)\n"
)

URLS = (
    "from django.urls import path, re_path, include\n"
    "from . import views\n"
    "urlpatterns = [\n"
    "    path('', views.home, name='home'),\n"
    "    path('books/<int:pk>/', views.book_detail),\n"
    "    path('api/', include('api.urls')),\n"
    "    re_path(r'^legacy/$', views.legacy),\n"
    "]\n"
)


class DjangoAnalyzerTests(unittest.TestCase):
    def test_models_fields_and_relationships_keep_source_lines(self):
        result = analyze_django("books/models.py", MODELS.encode("utf-8"))

        self.assertEqual(result["warnings"], [])
        self.assertEqual([model["name"] for model in result["models"]], ["Author", "Book"])
        author, book = result["models"]
        self.assertEqual((author["line"], book["line"]), (3, 5))
        self.assertEqual(
            [(field["name"], field["type"], field["line"]) for field in book["fields"]],
            [("title", "CharField", 6), ("author", "ForeignKey", 7),
             ("tags", "ManyToManyField", 8), ("owner", "OneToOneField", 9)],
        )
        self.assertEqual(
            [(relation["field"], relation["target"], relation["kind"], relation["line"])
             for relation in book["relationships"]],
            [("author", "Author", "ForeignKey", 7),
             ("tags", "Tag", "ManyToManyField", 8),
             ("owner", "settings.AUTH_USER_MODEL", "OneToOneField", 9)],
        )
        self.assertEqual(result["routes"], [])

    def test_direct_django_model_imports_are_recognized(self):
        source = (
            "from django.db.models import Model, CharField, ForeignKey\n"
            "class Article(Model):\n"
            "    title = CharField(max_length=80)\n"
            "    author = ForeignKey('Author', on_delete=None)\n"
        )
        result = analyze_django("articles/entities.py", source.encode("utf-8"))
        self.assertEqual([model["name"] for model in result["models"]], ["Article"])
        self.assertEqual(
            [(field["name"], field["type"]) for field in result["models"][0]["fields"]],
            [("title", "CharField"), ("author", "ForeignKey")],
        )
        self.assertEqual(result["models"][0]["relationships"][0]["target"], "Author")

    def test_urlpatterns_report_routes_and_includes(self):
        result = analyze_django("config/urls.py", URLS.encode("utf-8"))

        self.assertEqual(result["warnings"], [])
        self.assertEqual(
            [(route["path"], route["method"], route["kind"], route["line"])
             for route in result["routes"]],
            [("", "ANY", "route", 4),
             ("books/<int:pk>/", "ANY", "route", 5),
             ("api/", "ANY", "include", 6),
             ("^legacy/$", "ANY", "route", 7)],
        )
        self.assertEqual(result["routes"][0]["handler"], "views.home")
        self.assertIn("api.urls", result["routes"][2]["handler"])

    def test_unrelated_python_and_broken_syntax_do_not_create_facts(self):
        unrelated = (
            "class Fake(Model):\n"
            "    field = CharField()\n"
            "urlpatterns = [path('fake/', handler)]\n"
        )
        result = analyze_django("other.py", unrelated.encode("utf-8"))
        self.assertEqual(result["models"], [])
        self.assertEqual(result["routes"], [])

        broken = analyze_django("broken.py", b"def nope(:\n")
        self.assertEqual(broken["models"], [])
        self.assertEqual(broken["routes"], [])
        self.assertTrue(broken["warnings"])

    def test_project_scan_includes_django_facts(self):
        with tempfile.TemporaryDirectory(prefix="byakugan-django-") as directory:
            root = Path(directory)
            (root / "requirements.txt").write_text("Django>=4.2\n", encoding="utf-8")
            (root / "books").mkdir()
            (root / "books" / "models.py").write_text(MODELS, encoding="utf-8")
            (root / "config").mkdir()
            (root / "config" / "urls.py").write_text(URLS, encoding="utf-8")

            report = scan_project(root)
            self.assertEqual(report["summary"]["models"], 2)
            self.assertEqual(report["summary"]["routes"], 4)
            files = {file["path"]: file for file in report["files"]}
            self.assertEqual([model["name"] for model in files["books/models.py"]["models"]],
                             ["Author", "Book"])
            self.assertEqual(len(files["config/urls.py"]["routes"]), 4)
            self.assertEqual(report["warnings"], [])
            text = render_text(report)
            self.assertIn("Models (2):", text)
            self.assertIn("Book  books/models.py:5", text)
            self.assertIn("Routes (4):", text)
            self.assertIn("books/<int:pk>/", text)


if __name__ == "__main__":
    unittest.main()
