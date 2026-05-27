PRAGMA foreign_keys=OFF;
BEGIN TRANSACTION;
CREATE TABLE clients (
	id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	contact VARCHAR(200), 
	email VARCHAR(200), 
	phone VARCHAR(50), 
	address TEXT, 
	notes TEXT, 
	PRIMARY KEY (id)
);
INSERT INTO clients VALUES(1,'Baja Blast INC','T. Bell','TBell@fourthmeal.com',NULL,NULL,NULL);
CREATE TABLE venues (
	id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	city VARCHAR(100), 
	state VARCHAR(50), 
	country VARCHAR(100), 
	address TEXT, 
	dock_count INTEGER, 
	union_local VARCHAR(100), 
	wifi_ssid VARCHAR(200), 
	wifi_password VARCHAR(200), 
	notes TEXT, 
	PRIMARY KEY (id)
);
INSERT INTO venues VALUES(1,'Jacob K Javits Convention Center','New York','NY','USA','',NULL,NULL,NULL,NULL,NULL);
CREATE TABLE companies (
	id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	code VARCHAR(20), 
	type VARCHAR(50), 
	contact_name VARCHAR(200), 
	email VARCHAR(200), 
	phone VARCHAR(50), 
	address TEXT, 
	notes TEXT, 
	PRIMARY KEY (id)
);
INSERT INTO companies VALUES(1,'Owens',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
INSERT INTO companies VALUES(2,'Sparks',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
INSERT INTO companies VALUES(3,'BAV',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
INSERT INTO companies VALUES(4,'MRPM',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
INSERT INTO companies VALUES(5,'Tyler Scenic',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
INSERT INTO companies VALUES(6,'Creative Technology',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
INSERT INTO companies VALUES(7,'VRA',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
INSERT INTO companies VALUES(8,'Dallos Design',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
INSERT INTO companies VALUES(9,'Lumenarchy Inc',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
INSERT INTO companies VALUES(10,'Accelerator Scenic',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
INSERT INTO companies VALUES(11,'PSS',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
INSERT INTO companies VALUES(12,'ADI',NULL,'vendor',NULL,NULL,NULL,NULL,NULL);
CREATE TABLE positions (
	id INTEGER NOT NULL, 
	title VARCHAR(100) NOT NULL, 
	department VARCHAR(50), 
	type VARCHAR(30), 
	union_eligible BOOLEAN, 
	rate_low FLOAT, 
	rate_high FLOAT, 
	notes TEXT, 
	PRIMARY KEY (id)
);
INSERT INTO positions VALUES(1,'Executive Producer','Production','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(2,'Technical Director','Production','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(3,'Asst. Technical Director','Production','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(4,'Show Caller','Production','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(5,'Production Manager','Production','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(6,'Production Coordinator','Production','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(7,'Creative Producer','Production','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(8,'Art Director','Production','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(9,'Asst. Stage Manager','Production','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(10,'A1','Audio','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(11,'A2','Audio','hand',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(12,'Audio System Engineer','Audio','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(13,'SS Engineer','Audio','specialty',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(14,'Wireless Intercom Tech','Audio','specialty',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(15,'Audio Head','Audio','head',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(16,'Audio Hand','Audio','hand',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(17,'Video Director','Video','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(18,'EIC','Video','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(19,'E2 Engineer','Video','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(20,'Video TD','Video','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(21,'Camera Director','Video','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(22,'Camera Operator','Video','hand',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(23,'Jib Operator','Video','specialty',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(24,'GFX Operator','Video','hand',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(25,'Pixera Operator','Video','specialty',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(26,'Millumin Playback','Video','specialty',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(27,'Video Head','Video','head',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(28,'Video Hand','Video','hand',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(29,'Camera Op (Local)','Video','hand',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(30,'Lighting Designer','Lighting','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(31,'Master Electrician','Lighting','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(32,'Production Electrician','Lighting','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(33,'Asst. Production Electrician','Lighting','hand',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(34,'LX Programmer','Lighting','specialty',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(35,'Lighting Head','Lighting','head',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(36,'Lighting Hand','Lighting','hand',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(37,'LED Lead','LED','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(38,'LED Head','LED','head',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(39,'LED Hand','LED','hand',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(40,'Rigging PM','Rigging','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(41,'Lead Rigger','Rigging','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(42,'Lead Rigger (Laser Layout)','Rigging','specialty',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(43,'Rigger High','Rigging','hand',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(44,'Rigger Low','Rigging','hand',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(45,'Asst. Electrician','Rigging','hand',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(46,'Scenic Lead','Scenic','lead',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(47,'Scenic Assistant','Scenic','hand',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(48,'Scenic Head','Scenic','head',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(49,'Scenic Hand','Scenic','hand',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(50,'Carpenter Lead','Scenic','head',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(51,'Carpenter','Scenic','hand',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(52,'Steward','General','lead',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(53,'Labor Coordinator','General','lead',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(54,'Utility / Stagehand','General','utility',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(55,'Utility (Truss)','General','utility',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(56,'Loader','General','utility',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(57,'Forklift Driver','General','utility',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(58,'Boom Operator','General','utility',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(59,'Power','Power','hand',1,NULL,NULL,NULL);
INSERT INTO positions VALUES(60,'AI Caption Lead','Specialty','specialty',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(61,'Livestream Engineer','Specialty','specialty',0,NULL,NULL,NULL);
INSERT INTO positions VALUES(62,'Hair & Makeup','Specialty','specialty',0,NULL,NULL,NULL);
CREATE TABLE crew_members (
	id INTEGER NOT NULL, 
	first_name VARCHAR(100) NOT NULL, 
	last_name VARCHAR(100) NOT NULL, 
	company_id INTEGER, 
	position_id INTEGER, 
	email VARCHAR(200), 
	phone VARCHAR(50), 
	rate_standard FLOAT, 
	rate_ot FLOAT, 
	rate_dt FLOAT, 
	meal_penalty FLOAT, 
	per_diem FLOAT, 
	active BOOLEAN, 
	notes TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(company_id) REFERENCES companies (id), 
	FOREIGN KEY(position_id) REFERENCES positions (id)
);
INSERT INTO crew_members VALUES(1,'Allison','Ahmed',1,NULL,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(2,'Dana','Anderson',2,3,'danavanderson@me.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(3,'Lauren','Aquino',3,NULL,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(4,'Adam','Armstrong',4,24,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(5,'Jon','Ashner',4,61,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(6,'Gordon','Atcherson',5,15,'gordonatcherson@gmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(7,'Mariah','Baker',3,1,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(8,'Korbi','Bare',3,8,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(9,'Jon','Batz-Owings',6,21,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(10,'Dan','Bouchante',6,11,'danbouchante@gmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(11,'Dean','Brown',2,33,'dbrown9353@gmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(12,'Cherese','Campo',2,4,'ccampo11@me.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(13,'Jamie','Cherry',2,1,'jcherry@wearesparks.com','',155.0,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(14,'Brad','Criswell',3,34,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(15,'Enrique','Cruz',6,14,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(16,'Ryan','Cruz',7,41,'ryancruz704@gmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(17,'Bob','Dafnis',2,13,'bob@rd-productions.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(18,'Chris','Dallos',8,30,'chris@dallosdesign.com','917-287-0233',NULL,NULL,NULL,NULL,NULL,1,'');
INSERT INTO crew_members VALUES(19,'Robert','Davidson',4,6,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(20,'Mozique','Daviel',6,5,'mdaviel@ctus.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(21,'Andrew','DeMeo',9,32,'','(631) 873-6801',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(22,'Michael','Dewey',2,33,'mdewey@me.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(23,'Michael','Drexler',6,18,'mldrex@verizon.net','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(24,'Mark','Duman',3,5,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(25,'Kevin','Foote',10,15,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(26,'Jen','Furano',1,NULL,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(27,'Kerrilyn','Garma',2,21,'kmgarma@mac.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(28,'Brooks','Gotham',6,37,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(29,'Keenan','Hansen',6,13,'cyberkeenan@gmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(30,'Kentie','Heng',6,25,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(31,'Larry','Kargol',3,2,'lkargol@wearesparks.com','',155.0,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(32,'Matt','Kiehl',6,18,'mkiehl@ctus.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(33,'Andrey','Koulikov',6,19,'ak@redpixelconsulting.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(34,'Kevin','Leckey',2,3,'kevin.leckey@cmrtxconsultingllc.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(35,'Fred','Libertore',6,22,'fliberatore@ctus.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(36,'Sam','Llewellyn',3,31,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(37,'Luis','Castillo',6,37,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(38,'Dennis','Matsamuto',6,19,'dt.matsumoto427@gmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(39,'Nathan','McBee',6,14,'nmcbee@ngms.space','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(40,'Al','Miller',6,22,'amiller1917@hotmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(41,'Daniel','Molina',3,6,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(42,'Jose','Mora',2,10,'audiojose@gmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(43,'Ollie','Morrish',3,10,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(44,'Will','Odom',3,3,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(45,'Jimmy','Ostrom',6,12,'jostrom@ctus.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(46,'Scott','Pierog',6,12,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(47,'Brian','Pittman',5,51,'brianpittman00@gmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(48,'Katie','Purtiman',1,NULL,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(49,'Morgan','Reames',2,24,'morgan.reames@gmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(50,'Anne','Reid',4,1,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(51,'Mike','Reid',4,4,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(52,'Justin','Ritz',11,53,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(53,'Stephen','Roussel',6,19,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(54,'David','Soriano',6,22,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(55,'William','Spradling',4,26,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(56,'Rick','Steimer',7,41,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(57,'Grace','Stephenson',3,7,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(58,'Vince','Suhr',7,40,'vince@vegasrigg.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(59,'Dan','Sweeney',10,15,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(60,'Kevin','Tokunaga',6,20,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(61,'Dennis','Tracy',3,24,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(62,'Katie','Trotter',12,5,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(63,'Bob','Tubb',6,20,'visionmixer.tubb@gmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(64,'Brett','Tyrell',6,37,'thetrebleswitch@gmail.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(65,'Paul','Vogel',3,17,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(66,'Elliot','Wallace',6,18,'elliotwallace@bigshowllc.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(67,'James','Wilmoth',2,31,'jamesrwilmoth@me.com','',NULL,NULL,NULL,NULL,NULL,1,NULL);
INSERT INTO crew_members VALUES(68,'Jeff','Wong',6,21,'','',NULL,NULL,NULL,NULL,NULL,1,NULL);
CREATE TABLE shows (
	id INTEGER NOT NULL, 
	code VARCHAR(50), 
	name VARCHAR(200) NOT NULL, 
	client_id INTEGER, 
	venue_id INTEGER, 
	room_name VARCHAR(200), 
	load_in_date DATE, 
	show_start DATE, 
	show_end DATE, 
	strike_date DATE, 
	version INTEGER, 
	status VARCHAR(30), 
	notes TEXT, 
	created_at DATETIME, 
	updated_at DATETIME, 
	PRIMARY KEY (id), 
	FOREIGN KEY(client_id) REFERENCES clients (id), 
	FOREIGN KEY(venue_id) REFERENCES venues (id)
);
INSERT INTO shows VALUES(1,'TEST01','Test Show Scheduling Phase 1',1,1,'GENERAL SESSION','2026-05-25','2026-06-04','2026-06-05','2026-06-07',1,'Planning','This is a test show of the new ADI Workflow. ','2026-05-08 15:17:26.112282','2026-05-16 12:14:08.989640');
CREATE TABLE schedule_days (
	id INTEGER NOT NULL, 
	show_id INTEGER NOT NULL, 
	date DATE NOT NULL, 
	label VARCHAR(200), 
	call_time VARCHAR(20), 
	wrap_time VARCHAR(20), 
	phase VARCHAR(50), 
	milestones TEXT, 
	notes TEXT, travel_flight_number VARCHAR(20), travel_airline VARCHAR(100), travel_depart_airport VARCHAR(10), travel_arrive_airport VARCHAR(10), travel_depart_time VARCHAR(20), travel_arrive_time VARCHAR(20), travel_hotel_name VARCHAR(200), travel_hotel_confirm VARCHAR(100), 
	PRIMARY KEY (id), 
	FOREIGN KEY(show_id) REFERENCES shows (id)
);
INSERT INTO schedule_days VALUES(1,1,'2026-05-25','Load In Day 1','08:00','18:00','Load In','','',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(3,1,'2026-05-27',NULL,NULL,NULL,'Setup',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(4,1,'2026-05-28',NULL,NULL,NULL,'Setup',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(5,1,'2026-05-29',NULL,NULL,NULL,'Setup',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(6,1,'2026-05-30',NULL,NULL,NULL,'Setup',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(7,1,'2026-05-31',NULL,NULL,NULL,'Setup',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(8,1,'2026-06-01',NULL,NULL,NULL,'Setup',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(9,1,'2026-06-02',NULL,NULL,NULL,'Setup',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(10,1,'2026-06-03',NULL,NULL,NULL,'Setup',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(11,1,'2026-06-04',NULL,NULL,NULL,'Show Day',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(12,1,'2026-06-05',NULL,NULL,NULL,'Show Day',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(13,1,'2026-06-06',NULL,NULL,NULL,'Setup',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(14,1,'2026-06-07',NULL,NULL,NULL,'Strike',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
INSERT INTO schedule_days VALUES(15,1,'2026-05-26','Load In Day 1','08:00','18:00','Load In','','',NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL);
CREATE TABLE sub_schedule_entries (
	id INTEGER NOT NULL, 
	show_id INTEGER NOT NULL, 
	type VARCHAR(50) NOT NULL, 
	date DATE, 
	time VARCHAR(20), 
	activity VARCHAR(500), 
	duration_hrs FLOAT, 
	notes TEXT, 
	sort_order INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(show_id) REFERENCES shows (id)
);
CREATE TABLE schedule_activities (
	id INTEGER NOT NULL, 
	day_id INTEGER NOT NULL, 
	time VARCHAR(20), 
	description VARCHAR(500) NOT NULL, 
	notes TEXT, 
	sort_order INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(day_id) REFERENCES schedule_days (id)
);
INSERT INTO schedule_activities VALUES(1,1,'08:00','CREW START',NULL,10);
INSERT INTO schedule_activities VALUES(2,1,'10:30','MORNING BREAK — 15 min',NULL,20);
INSERT INTO schedule_activities VALUES(3,1,'13:00','LUNCH BREAK — 60 min',NULL,30);
INSERT INTO schedule_activities VALUES(4,1,'16:30','AFTERNOON BREAK — 15 min',NULL,40);
INSERT INTO schedule_activities VALUES(6,15,'08:00','CREW START',NULL,10);
INSERT INTO schedule_activities VALUES(7,15,'10:30','MORNING BREAK — 15 min',NULL,20);
INSERT INTO schedule_activities VALUES(8,15,'13:00','LUNCH BREAK — 60 min',NULL,30);
INSERT INTO schedule_activities VALUES(9,15,'16:30','AFTERNOON BREAK — 15 min',NULL,40);
INSERT INTO schedule_activities VALUES(10,15,'19:00','EOD WRAP',NULL,50);
INSERT INTO schedule_activities VALUES(11,1,'18:00','EOD WRAP','',50);
CREATE TABLE crew_rows (
	id INTEGER NOT NULL, 
	activity_id INTEGER NOT NULL, 
	sort_order INTEGER, 
	is_group_header BOOLEAN, 
	group_label VARCHAR(100), 
	qty INTEGER, 
	hours FLOAT, 
	position VARCHAR(100), 
	position_id INTEGER, 
	crew_member_id INTEGER, 
	name_override VARCHAR(200), 
	crew_type VARCHAR(50), 
	notes TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(activity_id) REFERENCES schedule_activities (id), 
	FOREIGN KEY(position_id) REFERENCES positions (id), 
	FOREIGN KEY(crew_member_id) REFERENCES crew_members (id)
);
INSERT INTO crew_rows VALUES(1,1,1,0,NULL,1,NULL,'LX Programmer',NULL,14,NULL,'Lead Crew',NULL);
INSERT INTO crew_rows VALUES(2,1,2,0,NULL,1,NULL,'Master Electrician',NULL,36,NULL,'Lead Crew',NULL);
INSERT INTO crew_rows VALUES(3,1,3,0,NULL,1,NULL,'Technical Director',NULL,31,NULL,'Lead Crew',NULL);
INSERT INTO crew_rows VALUES(4,1,4,0,NULL,1,NULL,'SS Engineer',NULL,29,NULL,'Lead Crew',NULL);
INSERT INTO crew_rows VALUES(5,6,1,0,NULL,1,NULL,'LX Programmer',NULL,14,NULL,'Lead Crew',NULL);
INSERT INTO crew_rows VALUES(6,6,2,0,NULL,1,NULL,'Master Electrician',NULL,36,NULL,'Lead Crew',NULL);
INSERT INTO crew_rows VALUES(7,6,3,0,NULL,1,NULL,'Technical Director',NULL,31,NULL,'Lead Crew',NULL);
INSERT INTO crew_rows VALUES(8,6,4,0,NULL,1,NULL,'SS Engineer',NULL,29,NULL,'Lead Crew',NULL);
CREATE TABLE production_phases (
	id INTEGER NOT NULL, 
	show_id INTEGER NOT NULL, 
	name VARCHAR(200) NOT NULL, 
	phase_type VARCHAR(50), 
	start_date DATE, 
	end_date DATE, 
	notes TEXT, 
	PRIMARY KEY (id), 
	FOREIGN KEY(show_id) REFERENCES shows (id)
);
INSERT INTO production_phases VALUES(1,1,'Prep','Prep','2026-05-25','2026-05-28','');
INSERT INTO production_phases VALUES(2,1,'Load In','Load In','2026-05-29','2026-06-03','');
INSERT INTO production_phases VALUES(3,1,'Show','Show','2026-06-04','2026-06-05','');
INSERT INTO production_phases VALUES(4,1,'Strike','Strike','2026-06-06','2026-06-07','');
CREATE TABLE day_templates (
	id INTEGER NOT NULL, 
	"key" VARCHAR(50) NOT NULL, 
	label VARCHAR(100) NOT NULL, 
	phase_hint VARCHAR(50), 
	activities_json TEXT, 
	sort_order INTEGER, 
	PRIMARY KEY (id), 
	UNIQUE ("key")
);
INSERT INTO day_templates VALUES(1,'load_in','Load In Day','Load In','[["8:00 AM", "CREW START"], ["10:00 AM", "COFFEE BREAK - 15 min"], ["12:30 PM", "LUNCH BREAK \u2014 30 min"], ["2:30 PM", "AFTERNOON BREAK \u2014 15 min"], ["6:00 PM", "EOD WRAP"]]',1);
INSERT INTO day_templates VALUES(2,'show_day','Show Day','Show','[["7:00 AM", "CREW START"], ["8:00 AM", "DOORS OPEN"], ["9:00 AM", "GENERAL SESSION BEGINS"], ["12:00 PM", "LUNCH BREAK \u2014 60 min"], ["1:00 PM", "AFTERNOON SESSION"], ["5:00 PM", "END OF SHOW"], ["7:00 PM", "EOD WRAP"]]',2);
INSERT INTO day_templates VALUES(3,'tech_rehearsal','Tech Rehearsal',NULL,'[["7:00 AM", "CREW START"], ["9:00 AM", "TECH REHEARSAL BEGINS"], ["12:30 PM", "LUNCH BREAK \u2014 30 min"], ["1:00 PM", "TECH REHEARSAL RESUMES"], ["5:00 PM", "END OF TECH"], ["7:00 PM", "EOD WRAP"]]',3);
INSERT INTO day_templates VALUES(4,'presenter_rehearsal','Presenter Rehearsal',NULL,'[["8:00 AM", "CREW START"], ["9:00 AM", "PRESENTER REHEARSAL BEGINS"], ["12:00 PM", "LUNCH BREAK \u2014 30 min"], ["1:00 PM", "PRESENTER REHEARSAL RESUMES"], ["5:00 PM", "END OF REHEARSAL"], ["7:00 PM", "EOD WRAP"]]',4);
INSERT INTO day_templates VALUES(5,'strike','Strike Day','Strike','[["8:00 AM", "CREW START \u2014 STRIKE BEGINS"], ["12:00 PM", "LUNCH BREAK \u2014 30 min"], ["6:00 PM", "STRIKE COMPLETE / EOD WRAP"]]',5);
INSERT INTO day_templates VALUES(6,'prep','Prep Day','Prep','[["8:00 AM", "CREW START \u2014 PREP"], ["12:30 PM", "LUNCH BREAK \u2014 60 min"], ["6:00 PM", "EOD WRAP"]]',6);
CREATE TABLE show_crew_assignments (
	id INTEGER NOT NULL, 
	show_id INTEGER NOT NULL, 
	crew_member_id INTEGER NOT NULL, 
	role_override VARCHAR(100), 
	created_at DATETIME, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_show_crew UNIQUE (show_id, crew_member_id), 
	FOREIGN KEY(show_id) REFERENCES shows (id), 
	FOREIGN KEY(crew_member_id) REFERENCES crew_members (id)
);
INSERT INTO show_crew_assignments VALUES(1,1,14,NULL,'2026-05-21 20:01:14.379302');
INSERT INTO show_crew_assignments VALUES(2,1,36,NULL,'2026-05-21 20:01:17.563093');
INSERT INTO show_crew_assignments VALUES(3,1,31,NULL,'2026-05-21 20:01:22.251021');
INSERT INTO show_crew_assignments VALUES(4,1,29,NULL,'2026-05-21 20:01:31.201065');
COMMIT;
