# tracker/urls.py
from django.urls import path
from . import views

urlpatterns = [
    path('', views.item_list, name="item_list"),
    path('add/', views.item_add, name="item_add"),
    path('edit/<int:pk>/', views.item_edit, name="item_edit"),
]
