"""Behavior tests for source links from Django URL patterns to views."""

from pathlib import Path
import tempfile
import unittest

from byakugan.cli import render_text
from byakugan.python.django.views_crawler import link_django_views
from byakugan.scan import scan_project


class DjangoViewLinkTests(unittest.TestCase):
    def setUp(self):
        self.temporary_directory = tempfile.TemporaryDirectory(prefix="byakugan-views-")
        self.addCleanup(self.temporary_directory.cleanup)
        self.root = Path(self.temporary_directory.name)

    def write(self, relative_path, content):
        destination = self.root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(content, encoding="utf-8")

    def routes(self, report):
        return {
            route["path"]: route
            for file in report["files"]
            for route in file.get("routes", [])
        }

    def test_sibling_function_and_class_views_link_to_source_lines(self):
        self.write(
            "books/urls.py",
            "from django.urls import path, include\n"
            "from . import views\n"
            "urlpatterns = [\n"
            "    path('books/', views.list_books),\n"
            "    path('books/<int:pk>/', views.BookView.as_view()),\n"
            "    path('api/', include('books.api_urls')),\n"
            "]\n",
        )
        self.write(
            "books/views.py",
            "def list_books(request):\n"
            "    return None\n"
            "\n"
            "class BookView:\n"
            "    def get(self, request):\n"
            "        return None\n",
        )

        report = scan_project(self.root)
        routes = self.routes(report)
        self.assertEqual(report["summary"]["routes"], 3)
        self.assertEqual(report["summary"]["resolvedViews"], 2)
        self.assertEqual(
            routes["books/"]["view"],
            {"path": "books/views.py", "name": "list_books", "line": 1, "kind": "function"},
        )
        self.assertEqual(
            routes["books/<int:pk>/"]["view"],
            {"path": "books/views.py", "name": "BookView", "line": 4, "kind": "class"},
        )
        self.assertNotIn("view", routes["api/"])
        rendered = render_text(report)
        self.assertIn("books/views.py:1", rendered)
        self.assertIn("books/views.py:4", rendered)

    def test_direct_import_alias_and_module_alias_resolve(self):
        self.write(
            "config/urls.py",
            "from django.urls import path\n"
            "from app.views import home as landing, DetailView as Detail\n"
            "import app.views as page_views\n"
            "urlpatterns = [\n"
            "    path('', landing),\n"
            "    path('detail/', Detail.as_view()),\n"
            "    path('health/', page_views.health),\n"
            "]\n",
        )
        self.write(
            "app/views.py",
            "async def home(request):\n"
            "    return None\n"
            "\n"
            "class DetailView:\n"
            "    pass\n"
            "\n"
            "def health(request):\n"
            "    return None\n",
        )

        report = scan_project(self.root)
        routes = self.routes(report)
        self.assertEqual(report["summary"]["resolvedViews"], 3)
        self.assertEqual(
            [(routes[name]["view"]["name"], routes[name]["view"]["line"], routes[name]["view"]["kind"])
             for name in ("", "detail/", "health/")],
            [("home", 1, "function"), ("DetailView", 4, "class"), ("health", 7, "function")],
        )
        self.assertTrue(all(routes[name]["view"]["path"] == "app/views.py" for name in ("", "detail/", "health/")))

    def test_relative_direct_import_resolves_without_executing_view(self):
        self.write(
            "app/urls.py",
            "from django.urls import path\n"
            "from .views import status as status_view\n"
            "urlpatterns = [path('status/', status_view)]\n",
        )
        self.write("app/views.py", "raise RuntimeError('must not run')\n\ndef status(request):\n    return None\n")

        report = scan_project(self.root)
        self.assertEqual(report["summary"]["resolvedViews"], 1)
        self.assertEqual(self.routes(report)["status/"]["view"], {
            "path": "app/views.py", "name": "status", "line": 3, "kind": "function",
        })

    def test_missing_or_ambiguous_view_stays_unlinked(self):
        self.write(
            "config/urls.py",
            "from django.urls import path, include\n"
            "from app.views import home\n"
            "from . import missing_views\n"
            "urlpatterns = [\n"
            "    path('home/', home),\n"
            "    path('missing/', missing_views.show),\n"
            "    path('api/', include('app.urls')),\n"
            "]\n",
        )
        self.write("service_a/app/views.py", "def home(request):\n    return None\n")
        self.write("service_b/app/views.py", "def home(request):\n    return None\n")

        report = scan_project(self.root)
        self.assertEqual(report["summary"]["routes"], 3)
        self.assertEqual(report["summary"]["resolvedViews"], 0)
        self.assertTrue(all("view" not in route for route in self.routes(report).values()))

    def test_disappearing_view_file_does_not_abort_linking(self):
        class DisappearingSources(dict):
            def __getitem__(self, path):
                if path == "app/views.py":
                    raise KeyError(path)
                return super().__getitem__(path)

        files = [{
            "path": "app/urls.py",
            "routes": [{"path": "home/", "method": "ANY", "handler": "views.home", "line": 3, "kind": "route"}],
        }]
        sources = DisappearingSources({
            "app/urls.py": b"from django.urls import path\nfrom . import views\nurlpatterns = [path('home/', views.home)]\n",
            "app/views.py": b"def home(request):\n    pass\n",
        })

        self.assertEqual(link_django_views(files, sources), 0)
        self.assertNotIn("view", files[0]["routes"][0])


if __name__ == "__main__":
    unittest.main()
