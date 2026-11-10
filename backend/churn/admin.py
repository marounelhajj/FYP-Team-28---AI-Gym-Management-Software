from django.contrib import admin

from .models import ChurnModel, ChurnRun, ChurnScore, RetentionCall

admin.site.register(ChurnModel)
admin.site.register(ChurnRun)
admin.site.register(ChurnScore)
admin.site.register(RetentionCall)
