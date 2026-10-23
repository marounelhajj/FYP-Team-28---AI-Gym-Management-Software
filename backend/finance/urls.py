from django.urls import path
from . import views

urlpatterns = [
    path("/report", views.financial_report),
    path("/expenses", views.expense_list),
    path("/meta", views.finance_meta),
]
