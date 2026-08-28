from django.contrib import admin
from .models import AppSetting, Classroom, ClassroomAction, Movement, Student

admin.site.register(Classroom)
admin.site.register(ClassroomAction)
admin.site.register(Student)
admin.site.register(Movement)
admin.site.register(AppSetting)
