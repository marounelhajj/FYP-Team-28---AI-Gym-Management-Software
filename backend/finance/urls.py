from django.urls import path
from . import views

urlpatterns = [
    path("/report", views.financial_report),
    path("/branch", views.branch_finances),
    path("/expenses/<int:expense_id>", views.expense_detail),
    path("/expenses", views.expense_list),
    path("/meta", views.finance_meta),
]
