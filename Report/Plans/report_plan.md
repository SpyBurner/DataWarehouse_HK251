Plan lack structure -> Requirements scattered -> Organize into execution batches.

### Batch 1: Build Pipeline Setup
- Create `Report/Plans/` directory structure.
- Update `docker-compose.yml` -> Add `texlive` service -> Mount `Report:/workspace` and `Report/Build:/workspace/Build`.
- Create `4_compile_report.bat` -> Map to docker compose command.
- Git commit.

### Batch 2: Template Migration
- Copy `Báo cáo DACN_HK251` structure to `Report/`.
- Remove template `.bat` files.
- Restructure TeX skeleton into new logical sections:
  1. Nguồn gốc dữ liệu (Skeleton only).
  2. Datawarehouse.
  3. Tiền xử lý dữ liệu.
  4. Feature Engineering.
  5. Xây dựng mô hình (Chọn mô hình, Nạp dữ liệu, Lưu trữ).
  6. Dự báo tương lai.
  7. Đánh giá (Gom cụm, Chất lượng - Skeleton only).
- Git commit.

### Batch 3: Document Pentaho
- Review `Pentaho/` directory.
- Update Pentaho pipeline description in `Plans/pentaho_pipeline_guide.md`.
- Git commit.

### Batch 4: Content Generation - Database & Processing
- Extract SQL schemas from `SQL/`.
- Write "Datawarehouse" section.
- Write "Tiền xử lý dữ liệu" section based on updated Pentaho guide.
- Git commit.

### Batch 5: Content Generation - Machine Learning
- Extract ML details from `ML_analytics/Data-pipeline.md`.
- Write "Feature Engineering" section.
- Write "Xây dựng mô hình" section (Selection, Training, Storage of Params/Super Params).
- Write "Dự báo tương lai" section.
- Git commit.