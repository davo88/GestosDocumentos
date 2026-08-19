# Generated manually on 2026-08-19

import gestor_documentos.models
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("gestor_documentos", "0017_wbsadjuntoimagen"),
    ]

    operations = [
        migrations.RenameField(
            model_name="wbsadjuntoimagen",
            old_name="imagen",
            new_name="archivo",
        ),
        migrations.AlterField(
            model_name="wbsadjuntoimagen",
            name="archivo",
            field=models.FileField(upload_to=gestor_documentos.models.wbs_task_attachment_upload_to),
        ),
        migrations.AlterModelOptions(
            name="wbsadjuntoimagen",
            options={
                "ordering": ["fecha_creacion", "id"],
                "verbose_name": "Adjunto WBS",
                "verbose_name_plural": "Adjuntos WBS",
            },
        ),
    ]
