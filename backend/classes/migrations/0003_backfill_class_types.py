from django.db import migrations

# Classes scheduled before class types existed get one: a type per branch and
# class name, holding as many people as the biggest of those classes did, so
# no existing class ends up over its type's maximum.


def backfill(apps, schema_editor):
    ClassType = apps.get_model("classes", "ClassType")
    GymClass = apps.get_model("classes", "GymClass")
    types = {}
    for gym_class in GymClass.objects.filter(class_type__isnull=True).order_by("starts_at", "id"):
        key = (gym_class.branch, gym_class.name.lower())
        class_type = types.get(key)
        if class_type is None:
            class_type = ClassType.objects.filter(branch=gym_class.branch, name__iexact=gym_class.name).first()
        if class_type is None:
            minutes = int((gym_class.ends_at - gym_class.starts_at).total_seconds() // 60)
            class_type = ClassType.objects.create(
                branch=gym_class.branch, name=gym_class.name, max_capacity=gym_class.capacity,
                default_duration_minutes=minutes,
            )
        elif gym_class.capacity > class_type.max_capacity:
            class_type.max_capacity = gym_class.capacity
            class_type.save(update_fields=["max_capacity"])
        types[key] = class_type
        gym_class.class_type = class_type
        gym_class.save(update_fields=["class_type"])


class Migration(migrations.Migration):
    dependencies = [
        ("classes", "0002_class_types"),
    ]

    operations = [migrations.RunPython(backfill, migrations.RunPython.noop)]
