# Prompt — Implementation Plan Auto-Generate Waypoint untuk Dua Copter

Kamu adalah senior software architect, geospatial engineer, robotics engineer, dan MAVLink/ArduPilot engineer. Baca **seluruh source code proyek Base Station BIMA SWARM UGM dan Companion Bridge** yang tersedia di workspace IDE sebelum menyusun rencana. Jangan menebak framework, nama file, API, state store, format mission, port, atau struktur data yang belum kamu temukan dari repository.

Tugasmu adalah membuat **implementation plan yang konkret, terperinci, dan siap dieksekusi** untuk menambahkan fitur **auto-generate waypoint** pada halaman `Swarm`. Saat ini UAV 03 dan UAV 04 hanya memiliki tombol `LOAD .waypoints`. Alur tersebut harus dikembangkan sehingga auto-generation menjadi alur utama, sedangkan upload file `.waypoints` tetap tersedia sebagai opsi manual/fallback.

> **Jangan mengedit source code pada tahap ini.** Audit repository terlebih dahulu, keluarkan implementation plan lengkap, lalu tunggu persetujuan sebelum melakukan implementasi.

## Kondisi UI dan alur yang sudah ada

Berdasarkan halaman `Swarm` saat ini:

- Terdapat swarm phase seperti `IDLE` dan safety interlock panel.
- Terdapat dua vehicle card: `UAV 03` berwarna oranye dan `UAV 04` berwarna merah muda.
- Masing-masing card menampilkan jumlah waypoint, status mission, dan tombol `LOAD .waypoints`.
- Terdapat tombol `UPLOAD MISSION TO BOTH UAVs` dan `START COORDINATED MISSION`.
- Upload mission dan Start Mission harus tetap menjadi dua tindakan berbeda. **Generate waypoint tidak boleh langsung meng-upload, arm, atau menerbangkan UAV.**
- Pertahankan identitas visual UAV 03/UAV 04 dan style UI yang sudah ada. Jangan melakukan redesign seluruh aplikasi di luar kebutuhan fitur ini.

## Tujuan utama

Alur utama baru harus menjadi:

```text
Tentukan area misi pada peta
→ Atur parameter survey
→ Generate dua mission otomatis
→ Validasi geometry dan konflik lintasan
→ Preview rute UAV 03 dan UAV 04
→ Konfirmasi
→ Upload mission ke kedua UAV
→ Start Coordinated Mission
```

Pengguna tidak lagi wajib membuat atau memilih dua file `.waypoints` secara manual. Dalam satu proses generate, sistem menghasilkan mission terpisah untuk UAV 03 dan UAV 04, lengkap dengan assignment yang deterministik dan aman.

## Batas scope versi pertama

Implementasi pertama harus fokus pada mission type **area survey berbentuk lawnmower/boustrophedon**, karena cocok untuk observasi area, pengambilan citra, dan proses stitching. Arsitektur boleh dibuat extensible untuk mission type lain, tetapi jangan memperbesar scope dengan membangun generic path planner yang tidak diperlukan.

Jika repository saat ini sudah memiliki peta, polygon editor, grid generator, atau mission planner pada halaman `Mission`, audit dan gunakan kembali logic/component tersebut. Jangan membuat implementasi kedua yang duplikatif.

## Input auto-generation

Rencana harus menentukan UI, validation, default, satuan, dan penyimpanan untuk input berikut:

1. Area survey berupa polygon yang digambar pada peta atau dipilih dari area yang sudah tersedia di Base Station.
2. Posisi/home UAV 03 dan UAV 04 dari telemetry yang valid atau input yang memang telah didukung aplikasi.
3. Survey altitude.
4. Ground speed target.
5. Lane/track spacing.
6. Desired image overlap atau footprint camera jika data kamera memang tersedia di project. Jika belum tersedia, gunakan lane spacing langsung dan jangan mengarang model kamera.
7. Sweep angle: `AUTO` sebagai default, dengan opsi manual bila diperlukan.
8. Waypoint acceptance radius/hold time apabila didukung mission schema saat ini.
9. Minimum horizontal dan vertical separation.
10. Safety margin terhadap boundary/geofence.
11. Mission ending behavior sesuai kemampuan yang sudah digunakan project: stop/hover, RTL, atau land. Jangan menetapkan salah satunya sebelum mengaudit alur mission yang ada.

Semua parameter harus configurable dan tidak boleh tersebar sebagai magic number.

## Algoritma pembentukan waypoint

Implementation plan harus menjelaskan algorithm pipeline berikut secara spesifik:

### 1. Validasi polygon

- Polygon memiliki minimal tiga vertex unik.
- Tidak self-intersecting.
- Luasnya tidak nol dan tidak terlalu kecil untuk dua UAV serta spacing yang dipilih.
- Seluruh vertex berada pada koordinat valid.
- Polygon tidak melanggar geofence/no-fly region yang tersedia.
- Tangani polygon convex maupun concave.

### 2. Konversi koordinat

Jangan melakukan perhitungan jarak, offset, atau intersection dalam meter menggunakan selisih latitude/longitude mentah. Konversikan WGS84 ke local metric frame seperti ENU/NED atau projected coordinate system yang sesuai, menggunakan common origin yang terdokumentasi. Setelah perhitungan selesai, konversikan hasil kembali ke latitude/longitude untuk `MISSION_ITEM_INT`.

Audit geospatial library yang sudah digunakan. Jangan menambah dependency baru apabila fungsi yang dibutuhkan sudah tersedia dan teruji di project.

### 3. Pemilihan arah sweep

Untuk mode `AUTO`, tentukan sweep direction yang meminimalkan jumlah turn, total route length, atau estimated mission time. Evaluasi pendekatan seperti longest-edge orientation, minimum rotated rectangle, atau candidate-angle search. Nyatakan metode yang dipilih dan alasan teknisnya.

Sweep angle manual harus menghasilkan output deterministik yang sama untuk input yang sama.

### 4. Pembuatan lawnmower path

- Buat parallel sweep lines dengan jarak sesuai lane spacing.
- Clip setiap line terhadap polygon, termasuk polygon concave yang dapat menghasilkan lebih dari satu segment.
- Urutkan segment menjadi pola bolak-balik/boustrophedon.
- Hindari waypoint duplikat, segment sangat pendek, dan turn yang tidak perlu.
- Semua survey waypoint harus berada di dalam polygon setelah safety margin diterapkan.
- Pertimbangkan transition/connector path antarsegment; connector tidak boleh diam-diam keluar dari geofence.
- Jangan memasukkan `TAKEOFF` ganda jika Companion Bridge saat ini sudah menjalankan `ARM → TAKEOFF → HOVER → AUTO`. Audit format mission yang diharapkan sebelum menentukan item pertama.

### 5. Pembagian pekerjaan untuk dua UAV

Hasil generator harus berupa satu `MissionBatch` yang berisi dua mission independen:

```text
MissionBatch
├── mission_uav_03
└── mission_uav_04
```

Pembagian area/rute harus memenuhi ketentuan berikut:

- Utamakan pembagian menjadi dua **blok strip yang berdekatan/contiguous**, bukan membagi lane secara selang-seling, agar UAV tidak terus-menerus menyilang.
- Seimbangkan estimated workload berdasarkan route distance dan estimated flight time, bukan hanya jumlah waypoint.
- Pertimbangkan jarak dari home/current position masing-masing UAV menuju entry point.
- Pilih entry point dan arah traversal setiap UAV untuk mengurangi connector crossing dan waktu kedatangan bersamaan pada area yang berdekatan.
- Assignment UAV 03 dan UAV 04 harus deterministik serta dapat dijelaskan.
- Mission kedua UAV tidak boleh berbagi waypoint identik kecuali hal tersebut memang diperlukan dan telah diberi temporal/vertical separation yang tervalidasi.
- Jangan mengubah assignment secara acak setiap kali tombol Generate ditekan dengan input yang sama.

Rencana harus menentukan objective/cost function pembagian, misalnya kombinasi:

```text
cost = w_distance × total_distance
     + w_balance × workload_difference
     + w_crossing × connector_crossings
     + w_conflict × predicted_conflict_penalty
     + w_turn × number_of_turns
```

Bobot harus configurable atau memiliki default terdokumentasi sebagai nilai awal SITL, bukan dianggap nilai final untuk flight test.

### 6. Penyusunan mission item

Generator harus menghasilkan internal mission model yang sama dengan jalur upload yang sudah digunakan. Audit parser `.waypoints`, data model, dan MAVLink uploader saat ini. Hindari dua representasi mission yang dapat berbeda hasilnya.

Tentukan secara eksplisit:

- MAVLink frame yang digunakan;
- command untuk navigation waypoint dan end behavior;
- sequence numbering;
- latitude/longitude scaling untuk `MISSION_ITEM_INT`;
- altitude semantics: relative, terrain, atau absolute;
- hold time, acceptance radius, autocontinue, dan parameter lain yang benar-benar digunakan;
- maximum waypoint count dan payload validation.

Generated mission harus bisa diekspor ke format `.waypoints` yang kompatibel dengan fitur manual yang sudah ada, sehingga pengguna dapat menyimpan, memeriksa, dan memuatnya kembali.

## Preflight trajectory deconfliction

Auto-generation harus menghasilkan mission yang secara desain sudah mengurangi konflik sebelum APF real-time bekerja. Tambahkan offline conflict checker yang mensimulasikan pergerakan kedua UAV secara sederhana berdasarkan route distance, speed, hold time, start delay, dan altitude.

Untuk sampled/piecewise-linear trajectory kedua UAV, hitung minimal:

- predicted position terhadap waktu;
- horizontal separation;
- vertical separation;
- closest point of approach;
- waktu terjadinya minimum separation;
- segment/waypoint yang menyebabkan konflik.

Jika konflik terdeteksi, generator harus mencoba strategi deterministik berikut sesuai constraint:

1. Mengubah entry point atau membalik arah traversal salah satu route.
2. Mengubah partition boundary agar workload tetap masuk akal.
3. Menambahkan start delay/staggered AUTO entry jika arsitektur start mission mendukungnya.
4. Menggunakan vertical separation hanya jika masih dalam altitude/geofence/mission constraint dan memang dipilih sebagai policy.
5. Jika tidak ada solusi valid, tandai generation sebagai gagal dan blok upload. Jangan menyembunyikan warning atau tetap menghasilkan mission berstatus aman.

APF runtime tetap digunakan untuk menangani deviasi nyata, angin, perbedaan kecepatan, atau keterlambatan. Jelaskan pembagian tanggung jawab:

- **Auto waypoint generator:** membentuk baseline mission dan menghilangkan konflik yang dapat diprediksi sebelum upload.
- **APF coordinator:** melakukan avoidance dinamis saat kedua UAV sudah terbang.
- **Hard safety layer:** minimum separation monitor, stale telemetry watchdog, geofence, bound checking, dan fallback mode.

Mission asli hasil generator harus immutable. Koreksi APF sementara tidak boleh menimpa baseline mission hingga terjadi waypoint drift kumulatif.

## Perubahan UI halaman Swarm

Buat rencana perubahan yang mengikuti component dan style aktual. Minimal mencakup:

### Mission planning panel

- Peta interaktif pada halaman `Swarm` atau reusable modal/drawer yang sesuai dengan layout saat ini.
- Tool menggambar, mengedit, dan menghapus polygon.
- Marker UAV 03/UAV 04, home position, serta freshness telemetry.
- Form parameter survey dengan unit dan validation yang jelas.
- Tombol utama `GENERATE WAYPOINTS`.
- Tombol `RESET AREA` dan `REGENERATE` bila plan sudah tersedia.
- Loading, error, warning, dan success state yang tidak hanya mengandalkan warna.

### Route preview

- Rute UAV 03 menggunakan warna oranye yang sudah ada.
- Rute UAV 04 menggunakan warna merah muda yang sudah ada.
- Nomor waypoint, arah perjalanan, entry/exit point, connector path, serta survey boundary.
- Conflict marker dan minimum predicted separation.
- Toggle show/hide route masing-masing UAV agar peta tidak terlalu penuh.
- Ringkasan per UAV: waypoint count, route distance, estimated time, altitude, lane count, mission source, dan validation status.

### Vehicle cards

Pada card UAV 03 dan UAV 04, pertahankan `LOAD .waypoints` sebagai opsi manual tetapi jadikan secondary action. Tambahkan atau tampilkan:

- badge `AUTO-GENERATED` atau `MANUAL`;
- waypoint count;
- generated/validated timestamp atau plan revision;
- route distance dan estimated duration;
- status `NOT GENERATED`, `GENERATING`, `VALID`, `WARNING`, atau `INVALID` sesuai state model proyek;
- aksi preview/edit/regenerate yang tidak membingungkan dengan upload.

### Tombol upload dan start

- `UPLOAD MISSION TO BOTH UAVs` hanya aktif setelah kedua mission valid dan telah dikonfirmasi.
- `START COORDINATED MISSION` tetap nonaktif sampai upload kedua UAV diterima serta seluruh safety interlock lulus.
- Mengubah polygon atau parameter setelah mission di-upload harus menandai plan sebagai dirty/stale dan mewajibkan generate serta upload ulang.
- Jangan pernah mengaktifkan Start hanya karena generate sukses.

## State dan data model

Audit state management yang digunakan, lalu rencanakan perluasan state tanpa membuat source of truth ganda. Minimal pertimbangkan:

```text
PlanningState:
  EMPTY
  EDITING_AREA
  GENERATING
  GENERATED
  VALIDATING
  VALID
  INVALID
  DIRTY

MissionSource:
  AUTO_GENERATED
  MANUAL_FILE
```

Tentukan data model konkret untuk:

- `SurveyArea`;
- `SurveyParameters`;
- `GeneratedRoute`;
- `PerUAVMissionPlan`;
- `MissionBatch`;
- `TrajectoryConflict`;
- `GenerationDiagnostics`;
- plan version/hash untuk mendeteksi stale upload.

Mission yang ditampilkan, divalidasi, diekspor, dan dikirim ke uploader harus berasal dari data yang sama.

## Dampak pada Base Station

Setelah audit repository, rencana wajib menyebut file, class, function, component, store, hook, API, dan test aktual yang akan dibuat atau diubah untuk:

1. Map/polygon editor.
2. Survey parameter form.
3. Coordinate conversion.
4. Polygon validation dan clipping.
5. Lawnmower path generator.
6. Two-UAV workload partitioner.
7. Entry/exit optimizer.
8. Offline trajectory conflict checker.
9. Mission item builder.
10. Route preview layer.
11. Plan versioning dan dirty-state detection.
12. Integration dengan dual-UAV mission uploader.
13. Export/import `.waypoints`.
14. Logging generation input, output, score, warning, dan validation result.

Generator, partitioner, dan conflict checker harus dipisahkan dari UI agar dapat diuji secara deterministik dan dijalankan ulang dari log/test fixture.

## Dampak pada Companion Bridge

Auto-generation sebaiknya terjadi di Base Station; jangan menduplikasi geospatial planner pada setiap Raspberry Pi. Namun audit Companion Bridge dan masukkan perubahan yang memang diperlukan agar generated mission aman dipakai:

1. Pastikan generated mission masuk melalui protocol upload yang sama dengan mission manual.
2. Validasi `MISSION_COUNT`, sequence, frame, command, altitude, coordinate range, dan maximum item count.
3. Pastikan mission UAV 03 tidak dapat diterima/diterapkan oleh bridge UAV 04 dan sebaliknya.
4. Kaitkan mission accepted dengan UAV identity serta plan revision/hash jika protocol aplikasi saat ini memungkinkan.
5. Laporkan accepted waypoint count dan validation error secara jelas ke Base Station.
6. Pertahankan urutan `ARM → TAKEOFF → HOVER → AUTO` dan jangan menjalankan mission saat baru selesai generate/upload.
7. Pastikan APF correction dapat kembali ke baseline generated mission tanpa kehilangan current mission progress.
8. Tambahkan logging source mission (`AUTO_GENERATED`/`MANUAL`) jika metadata tersebut tersedia pada layer aplikasi.

Jika hasil audit menunjukkan Companion Bridge tidak perlu perubahan untuk bagian tertentu karena generated mission identik dengan mission manual pada level MAVLink, tuliskan hal itu secara eksplisit beserta buktinya. Jangan mengubah bridge hanya agar terlihat ada perubahan.

## Manual waypoint tetap didukung

Fitur `LOAD .waypoints` tidak boleh dihapus. Rencana harus mempertahankan:

- import satu mission untuk masing-masing UAV;
- validation yang sama seperti generated mission;
- preview pada peta sebelum upload;
- deteksi conflict antarmission manual;
- source badge `MANUAL`;
- kemampuan mengganti mission manual dengan hasil auto-generation dan sebaliknya tanpa state lama tertinggal.

Baik manual maupun generated mission harus melewati satu validation dan upload pipeline yang sama.

## Safety interlock tambahan

Selain interlock yang sudah ada, upload harus diblokir apabila:

- polygon atau parameter tidak valid;
- home/current position yang diperlukan belum valid atau stale;
- salah satu route kosong;
- waypoint berada di luar polygon/geofence setelah tolerance;
- frame atau altitude semantics ambigu;
- plan telah berubah setelah validation;
- mission assignment tidak cocok dengan UAV identity;
- terdapat conflict yang belum terselesaikan;
- route distance/estimated duration melewati limit yang dikonfigurasi;
- jumlah waypoint melewati kemampuan FC/project;
- hasil konversi koordinat memiliki NaN, infinity, atau range tidak valid.

Jangan klaim auto-generated mission pasti bebas tabrakan. Tampilkan bahwa plan telah lolos pemeriksaan berdasarkan parameter dan model prediksi yang digunakan.

## Pengujian yang wajib direncanakan

### Unit test geometry dan generator

- polygon convex, concave, sangat sempit, dan rotated;
- polygon self-intersecting dan duplicate vertex;
- lane spacing lebih besar daripada lebar area;
- clipping menghasilkan beberapa segment;
- sweep angle otomatis dan manual;
- tidak ada waypoint di luar safety boundary;
- tidak ada duplicate/NaN waypoint;
- hasil deterministik untuk input yang sama;
- coordinate conversion dan round-trip error dalam tolerance.

### Unit test pembagian dua UAV

- workload seimbang dalam tolerance;
- pembagian strip contiguous;
- home UAV berada pada sisi area yang berbeda maupun sama;
- connector crossing mendapatkan penalty;
- route assignment stabil untuk input sama;
- area terlalu kecil untuk dua UAV ditolak dengan alasan yang jelas.

### Unit test conflict checker

- rute paralel aman;
- head-on;
- crossing pada waktu sama dan waktu berbeda;
- altitude berbeda;
- satu UAV memiliki hold/delay;
- minimum separation terjadi di tengah segment, bukan tepat pada waypoint;
- solusi reverse route, repartition, delay, atau vertical separation tervalidasi ulang.

### Integration test Base Station

- gambar area → generate → preview → validate → upload;
- edit polygon setelah generate menghasilkan `DIRTY`;
- regenerate mengganti kedua route secara atomik;
- manual import dan auto-generation memakai pipeline yang sama;
- satu mission valid dan satu invalid memblokir upload;
- export `.waypoints` kemudian import menghasilkan mission ekuivalen;
- refresh/reconnect tidak membuat plan lama dianggap telah di-upload.

### SITL dua ArduCopter

Gunakan dua instance SITL dengan endpoint dan `SYSID` berbeda. Uji:

1. area persegi sederhana;
2. area concave;
3. home UAV pada sisi yang sama;
4. connector route berpotensi menyilang;
5. kecepatan aktual kedua UAV berbeda;
6. satu UAV terlambat masuk `AUTO`;
7. APF aktif ketika trajectory aktual menyimpang;
8. generated mission diekspor lalu dimuat secara manual;
9. route diubah setelah upload;
10. telemetry atau Base Station terputus.

## Acceptance criteria minimum

- Pengguna dapat menggambar satu area, mengisi parameter, dan menekan satu tombol Generate untuk memperoleh dua mission tanpa file eksternal.
- UAV 03 dan UAV 04 menerima rute berbeda yang membagi area secara jelas dan deterministik.
- Seluruh waypoint tervalidasi berada dalam boundary/geofence yang diizinkan.
- Workload difference dan predicted minimum separation ditampilkan serta dibandingkan dengan threshold konfigurasi.
- Konflik yang belum terselesaikan memblokir upload.
- Hasil route terlihat pada peta dengan warna yang konsisten dengan card UAV.
- Generated mission dapat diekspor ke `.waypoints` dan di-import kembali tanpa perubahan semantik.
- Manual upload tetap berfungsi.
- Generate tidak menyebabkan upload, arm, perubahan mode, atau Start Mission.
- Upload ke kedua UAV tetap memerlukan `MISSION_ACK` yang benar dari masing-masing UAV.
- Start tetap memerlukan readiness barrier dan safety interlock.
- APF runtime menggunakan generated route sebagai baseline tanpa memodifikasi mission asli secara kumulatif.
- Seluruh keputusan generator dan conflict checker dapat direkonstruksi dari log.

## Format keluaran implementation plan

Keluarkan dokumen dengan urutan berikut:

1. **Repository audit summary** — stack, entry point, halaman Swarm, halaman Mission, map library, mission parser/uploader, state store, Companion Bridge, dan test setup.
2. **Current workflow and gaps** — jelaskan alur `LOAD .waypoints` yang sekarang dan bagian yang perlu dipertahankan.
3. **Target user workflow** — dari polygon input sampai Start Coordinated Mission.
4. **Target architecture and data flow**.
5. **Waypoint generation algorithm** — geometry, sweep, clipping, ordering, mission item construction.
6. **Two-UAV partition and optimization design**.
7. **Offline conflict detection and resolution design**.
8. **Integration with APF runtime and safety interlocks**.
9. **UI/UX change plan** sesuai tampilan UAV 03/UAV 04 saat ini.
10. **Base Station file-by-file plan** dengan nama file dan symbol aktual.
11. **Companion Bridge file-by-file plan**, termasuk bagian yang tidak perlu diubah beserta alasannya.
12. **Data model, state machine, API, and configuration changes**.
13. **Manual import/export compatibility plan**.
14. **Logging and observability plan**.
15. **Unit, integration, and two-vehicle SITL test plan**.
16. **Implementation order** dalam tahap kecil yang buildable dan testable.
17. **Risks, assumptions, unresolved decisions, and rollback plan**.
18. **Definition of Done** berupa checklist terukur.

Untuk setiap langkah implementasi, tuliskan:

- tujuan langkah;
- file dan symbol yang terdampak;
- data model/API yang berubah;
- dependency;
- risiko dan rollback;
- test yang membuktikan langkah selesai.

Hindari kalimat generik seperti “buat generator waypoint” atau “tambahkan map”. Gunakan nama file, component, function, class, service, handler, dan store yang benar-benar ditemukan di repository. Bedakan fakta hasil audit dengan asumsi. Bila fitur peta atau source Companion Bridge tidak tersedia di workspace, sebutkan tepat bagian yang hilang dan lanjutkan audit pada bagian yang tersedia tanpa mengarang struktur proyek.

Mulai dengan membaca repository secara menyeluruh. Setelah itu tampilkan implementation plan lengkap dan **tunggu persetujuan sebelum mengedit kode**.