# Seed load report

Generated 03-11-2026 18:18 by `python -m seed.build`. Every judgement the builder made is listed here; nothing was filled silently.

## Summary

| Item | Count |
|---|---|
| Offices | 76 (ACMR_OFFICE: 2, BLOCK_VET_OFFICE: 5, CIRCLE_OFFICE: 32, DC_OFFICE: 5, DEPT_DISTRICT_OFFICE: 1, DEPT_STATE_OFFICE: 1, DISTRICT_AGRICULTURE_OFFICE: 2, DISTRICT_VET_OFFICE: 2, EMPLOYMENT_EXCHANGE: 2, SUBDIV_OFFICE: 20, SUB_REGISTRAR_OFFICE: 4) |
| Chairs (sanctioned posts, all `derived = true`) | 128 |
| Officers | 128 (real 84, demo 44 = 34.4%) |
| Function allotments | 201 (demo 131) |

Source priority when sources disagree: `List_of_DCs.xlsx` > Nagaon work-allotment order > IAS/ACS gradation lists. Gradation lists add ADC and AC holders (the DC list names only one ADC per district) and supply batch year for seniority. DC, CDC and CO chairs come only from `List_of_DCs.xlsx`.

## Missing inputs

- `Sewa_Setu_MDM_Reference.xlsx` was not supplied.
- Instead, office IDs come from the **MDM PoC** (`data/mdm_snapshot/`, MDM version 39019, updated 2026-11-03T18:06:37.261Z). Offices MDM does not have keep provisional IDs.
- `Officer_and_Posting_List.xlsx` was not supplied; the IAS and ACS gradation lists (August 2026) are used for batch year and current posting instead.

## Name variants merged as one person (fuzzy match)

- 'Sontosh Kr. Nath' (List_of_DCs.xlsx COs!row73.1) = 'Sontush kumar Nath' (similarity 0.94; same mobile)
- 'Hemanga Nobis' (ACS_Gradation_List_Aug_2026.xlsx row428) = 'Hemanga Nabish' (similarity 0.88; same district)
- 'Ranjumani Dutta' (ACS_Gradation_List_Aug_2026.xlsx row481) = 'Ranjumoni Dutta' (similarity 0.93; same mobile)
- 'Swapneel Paul' (IAS_Gradation_List_Aug_2026.xlsx row135) = 'Swapnil Paul' (similarity 0.87; same mobile)
- 'Nibedan Das Patwary' (ACS_Gradation_List_Aug_2026.xlsx row65) = 'Nivedan Das Patowari' (similarity 0.86; same district)
- 'Gauranga Dutta' (ACS_Gradation_List_Aug_2026.xlsx row558) = 'Gouranga Dutta' (similarity 0.92; same mobile)

## Gaps filled from the earlier PoC (cross-check file)

- List_of_DCs.xlsx CDC!row26.4: CDC 'Phyllis V L Hmunsiami Hrangchal' has no co-district in the list; `Sewa_Setu_PoC_Linked_Masters.xlsx` places them at Digboi.

## Rows not seeded (no post code)

- Officers_Workallotment_13_03_26.pdf Sl 1: 'Debajani Choudhury' (District Development Commissioner, Nagaon) — District Development Commissioner is not in the post code list
- Officers_Workallotment_13_03_26.pdf Sl 10: 'Tejas Agnihotri' (Assistant. District Commissioner, Nagaon) — Assistant District Commissioner (IAS trainee) is not in the post code list

## Source disagreements (List_of_DCs.xlsx used)

- DC Dhubri (Dhubri): gradation list (IAS_Gradation_List_Aug_2026.xlsx row132) names 'Dibakar Nath'; List_of_DCs.xlsx names 'Megha NidhiDahal'.
- CDC Golakganj (Dhubri): gradation list (ACS_Gradation_List_Aug_2026.xlsx row264) names 'Kartik Kalita'; List_of_DCs.xlsx names 'Yimkum I. Ozukum'.
- CDC Jalukbari (Kamrup Metropolitan): gradation list (ACS_Gradation_List_Aug_2026.xlsx row364) names 'Dr. Jiwan Krishna Goswami'; List_of_DCs.xlsx names 'Apurba Kr. Das'.
- CDC Makum (Tinsukia): gradation list (ACS_Gradation_List_Aug_2026.xlsx row488) names 'Niluram Sharma'; List_of_DCs.xlsx names 'Jangmir Rongpharpi'.

## Conflicting postings across sources

- 'Jangmir Rongpharpi': ACS_Gradation_List_Aug_2026.xlsx row474 says ADC at Tinsukia (Tinsukia); seeded at CDC at Makum (Tinsukia) (List_of_DCs.xlsx CDC!row26.5, higher-priority source).
- 'Ranjumoni Dutta': ACS_Gradation_List_Aug_2026.xlsx row481 says ADC at Dhubri (Dhubri); seeded at CO at Athani (Dhubri) (List_of_DCs.xlsx COs!row7.1, higher-priority source).
- 'Sari Lalruotkim Lungtau': ACS_Gradation_List_Aug_2026.xlsx row513 says ADC at Dhubri (Dhubri); seeded at CO at Bilasipara (Dhubri) (List_of_DCs.xlsx COs!row9.1, higher-priority source).
- 'Biswajit Dutta': ACS_Gradation_List_Aug_2026.xlsx row607 says AC at Nagaon (Nagaon); seeded at CO at Raha (Nagaon) (List_of_DCs.xlsx COs!row71.1, higher-priority source).
- 'Nimashri Dauka': ACS_Gradation_List_Aug_2026.xlsx row554 says AC at Tinsukia (Tinsukia); seeded at CO at Sadiya (Tinsukia) (List_of_DCs.xlsx COs!row124.1, higher-priority source).

## Officer listed in two offices

- 'Jayanta Dutta': List_of_DCs.xlsx COs!row4.1 says CO at Gauripur (Dhubri); seeded at ADC at Dhubri (Dhubri) (List_of_DCs.xlsx ADC!row8). The CO at Gauripur (Dhubri) chair is filled by a demo officer.
- 'Sontush kumar Nath': List_of_DCs.xlsx COs!row73.1 says CO at Rupahi (Nagaon); seeded at CO at Barkhetri (Nalbari) (List_of_DCs.xlsx COs!row39.1). The CO at Rupahi (Nagaon) chair is filled by a demo officer.

## Circle offices cross-walked to PoC_master_data.xlsx Geo Master

- RCO-11SOU 'South Salmara (Pt)' (List_of_DCs.xlsx) = DHB-C08 'SOUTH SHALAMARA (PART)' (spelling differs; MDM to settle the official name)
- RCO-11GOL 'Golakganj' (List_of_DCs.xlsx) = DHB-C07 'GOLAKAGANZ' (spelling differs; MDM to settle the official name)
- RCO-11CHA 'Chapar' (List_of_DCs.xlsx) = DHB-C03 'CHAPOR' (spelling differs; MDM to settle the official name)
- RCO-20CHA 'Chandrapur' (List_of_DCs.xlsx) = KMM-C04 'SANDRAPUR' (spelling differs; MDM to settle the official name)
- RCO-26SAD 'Sadar Nagaon' (List_of_DCs.xlsx) = NGN-C05 'NAGAON' (spelling differs; MDM to settle the official name)
- RCO-26KAM 'Kampur' (List_of_DCs.xlsx) = NGN-C04 'KAMAPUR' (spelling differs; MDM to settle the official name)
- RCO-26KAL 'Kaliabor' (List_of_DCs.xlsx) = NGN-C01 'KALIABAR' (spelling differs; MDM to settle the official name)
- RCO-27NAL 'Nalbari' (List_of_DCs.xlsx) = NLB-C05 'NALABARI' (spelling differs; MDM to settle the official name)
- RCO-33SAD 'Sadiya' (List_of_DCs.xlsx) = TSK-C02 'SADIA' (spelling differs; MDM to settle the official name)

## Circle offices with no officer on the roster

- RCO-26SAK 'Samaguri (K)' (NGN-C02): in the Geo Master circle list, but no Circle Officer is named in List_of_DCs.xlsx. Office seeded with no chairs; seat lookups there return NO_HOLDER until a posting is entered.

## Offices cross-walked to the MDM PoC

- 'Nalbari' (sources) = MDM AS-CR-298-05 'Office of the Circle Officer, Nalabari' (spelling differs; provisional ID would have been RCO-27NAL)
- 'Bilashipara' (sources) = MDM SDO_D-285-BILASI 'Co-District Office, Bilasipara' (spelling differs; provisional ID would have been CDO-11BIL)
- 'South Salmara (Pt)' (sources) = MDM AS-CR-285-08 'Office of the Circle Officer, South Shalamara(Part)' (spelling differs; provisional ID would have been RCO-11SOU)
- 'Golakganj' (sources) = MDM AS-CR-285-07 'Office of the Circle Officer, Golakaganz' (spelling differs; provisional ID would have been RCO-11GOL)
- 'Chapar' (sources) = MDM AS-CR-285-04 'Office of the Circle Officer, Chapor' (spelling differs; provisional ID would have been RCO-11CHA)
- 'Sadiya' (sources) = MDM AS-CR-302-03 'Office of the Circle Officer, Sadia' (spelling differs; provisional ID would have been RCO-33SAD)
- 'Sadar Nagaon' (sources) = MDM CO_NAGAON 'Nagaon Revenue Circle Office' (spelling differs; provisional ID would have been RCO-26SAD)
- 'Kampur' (sources) = MDM AS-CR-297-03 'Office of the Circle Officer, Kamapur' (spelling differs; provisional ID would have been RCO-26KAM)

## MDM offices with no officer on the HR roster (added with no chairs)

- Nalbari: DAO_D-298, SDO_D-298-SDR
- Kamrup Metropolitan: ACMR_KMM, BVO_DIMORIA, BVO_RANI, DAO_KMM, DVO_KMM, EE_KMM, SDO_KMM-GUW, SDO_KMM-NEW, SDO_KMM-SNP, SR_KMM-GUW, SR_KMM-SNP
- Dhubri: SDO_D-285-SDR
- Tinsukia: SDO_D-302-SDR
- Nagaon: ACMR_NGN, BVO_KALIABOR, BVO_PAKHIMORIA, BVO_RAHA, DAO_NGN, DVO_NGN, EE_NGN, SDO_NGN-SDR, SR_NGN-KLB, SR_NGN-SDR

## Offices not in MDM (provisional IDs kept)

- CDO-20NEW 'Co-District Office, New Ghy' (Kamrup Metropolitan): no SUBDIV_OFFICE of that name in MDM.
- ACMR-00ASM 'Assam Council of Medical Registration (state office)': the MDM PoC has no such office yet.

## Posts mapped to MDM designations

- DC → DISTRICT_COMMISSIONER
- ADC → ADC
- CDC → CO_DISTRICT_COMMISSIONER
- AC → ASSISTANT_COMMISSIONER
- CO → CIRCLE_OFFICER
- SR → SUB_REGISTRAR
- DAO → no MDM designation yet
- REG → no MDM designation yet
- PRES → no MDM designation yet

## Demo officers (no source data)

- DAO_D-298 DAO: no officer named in any source; demo officer seeded.
- ACMR-00ASM REG: no officer named in any source; demo officer seeded.
- ACMR-00ASM PRES: no officer named in any source; demo officer seeded.

## Names taken from PoC_master_data.xlsx

- ACMR-00ASM: department code ACM = 'Assam Council of Medical Registration'.

## Issuing departments checked against the official department list

- On the Official Dept List: Agriculture Department, Personnel Department, Revenue & Disaster Management Department.

## Nagaon allotments not seeded (BR-04: no posting in DCO Nagaon)

- 'Debajani Choudhury' (District Development Commissioner, Nagaon): DECENTRALIZED_PLANNING, CENSUS

## Nagaon allotment lines not mapped to a function

- Raj Boruah: 'He will manage all tasks related to the Kaliabor Co-district and delegate responsibilities to his subordinate officers.'
- Ankita Bora: 'She will manage all tasks related to the Raha Co-district and delegate responsibilities to her subordinate officers.'

## Demo officers for function coverage

- AS-D-298: no real allotment of SOCIAL_WELFARE, E_GOVERNANCE; demo ADC 'Demo Officer NAL-1' seeded holding it.
- AS-D-298: no real allotment of ARTPS; demo ADC 'Demo Officer NAL-2' seeded holding it.
- DC_KMM: no real allotment of SOCIAL_WELFARE, E_GOVERNANCE; demo ADC 'Demo Officer KMM-1' seeded holding it.
- DC_KMM: no real allotment of ARTPS; demo ADC 'Demo Officer KMM-2' seeded holding it.
- AS-D-285: no real allotment of SOCIAL_WELFARE, E_GOVERNANCE; demo ADC 'Demo Officer DHU-1' seeded holding it.
- AS-D-285: no real allotment of ARTPS; demo ADC 'Demo Officer DHU-2' seeded holding it.
- AS-D-302: no real allotment of SOCIAL_WELFARE, E_GOVERNANCE; demo ADC 'Demo Officer TIN-1' seeded holding it.
- AS-D-302: no real allotment of ARTPS; demo ADC 'Demo Officer TIN-2' seeded holding it.

## Demo function bundles (offices with no real allotment order)

- AS-D-285 ADC 'Devajyoti Gogoi': bundle 1 = ELECTION, REVENUE, LAND_ACQUISITION, RKG, RECORD_ROOM, PERSONNEL, FOREST, SKILL_DEVELOPMENT
- AS-D-285 ADC 'Ripanjyoti Nath': bundle 2 = SUBDIVISIONAL_PLANNING, RURAL_DEVELOPMENT, POWER, PHE, RTI, BAKIJAI, ORUNUDOI
- AS-D-285 ADC 'Jayanta Dutta': bundle 3 = MAGISTRACY, DEVELOPMENT, EDUCATION, FPDCA, AGRICULTURE, SPORTS, LINE_DEPARTMENTS
- AS-D-298 ADC 'Moushumi Chetia': bundle 1 = ELECTION, REVENUE, LAND_ACQUISITION, RKG, RECORD_ROOM, PERSONNEL, FOREST, SKILL_DEVELOPMENT
- AS-D-298 ADC 'Sudeep Nath': bundle 2 = SUBDIVISIONAL_PLANNING, RURAL_DEVELOPMENT, POWER, PHE, RTI, BAKIJAI, ORUNUDOI
- AS-D-298 ADC 'Partha Pratim Khanikar': bundle 3 = MAGISTRACY, DEVELOPMENT, EDUCATION, FPDCA, AGRICULTURE, SPORTS, LINE_DEPARTMENTS
- AS-D-298 ADC 'Kaustav Kalita': bundle 4 = RELIEF_REHABILITATION, DISASTER_MGMT, EXCISE, AADHAAR
- AS-D-298 ADC 'Kaustubh Roy': bundle 5 = HEALTH_FW, SUBDIVISIONAL_WELFARE, WOMEN_CELL
- AS-D-298 ADC 'Shilpi Shikha Thakuria': bundle 6 = NAZARAT, URBAN_AFFAIRS, CULTURAL_AFFAIRS, ACCOUNTS
- AS-D-298 AC 'Jebin Gulnar': bundle 1 = ELECTION, ORUNUDOI
- AS-D-302 ADC 'Pankaj Kr. Nagbanshi': bundle 1 = ELECTION, REVENUE, LAND_ACQUISITION, RKG, RECORD_ROOM, PERSONNEL, FOREST, SKILL_DEVELOPMENT
- AS-D-302 ADC 'Mondira Boruah': bundle 2 = SUBDIVISIONAL_PLANNING, RURAL_DEVELOPMENT, POWER, PHE, RTI, BAKIJAI, ORUNUDOI
- AS-D-302 ADC 'Sanghamitra Baruah': bundle 3 = MAGISTRACY, DEVELOPMENT, EDUCATION, FPDCA, AGRICULTURE, SPORTS, LINE_DEPARTMENTS
- AS-D-302 ADC 'Himadri Borah': bundle 4 = RELIEF_REHABILITATION, DISASTER_MGMT, EXCISE, AADHAAR
- AS-D-302 AC 'Sudip Gogoi': bundle 1 = ELECTION, ORUNUDOI
- DC_KMM ADC 'Jonti Deka': bundle 1 = ELECTION, REVENUE, LAND_ACQUISITION, RKG, RECORD_ROOM, PERSONNEL, FOREST, SKILL_DEVELOPMENT
- DC_KMM ADC 'Hemanga Nabish': bundle 2 = SUBDIVISIONAL_PLANNING, RURAL_DEVELOPMENT, POWER, PHE, RTI, BAKIJAI, ORUNUDOI
- DC_KMM ADC 'Bubul Baishya': bundle 3 = MAGISTRACY, DEVELOPMENT, EDUCATION, FPDCA, AGRICULTURE, SPORTS, LINE_DEPARTMENTS
- DC_KMM ADC 'Raja Baishya': bundle 4 = RELIEF_REHABILITATION, DISASTER_MGMT, EXCISE, AADHAAR
- SDO_D-302-SAD AC 'Abhijat Borah': bundle 1 = MAGISTRACY, REVENUE, ELECTION, RTI
- SDO_NGN-KLB AC 'Neihat Haolai': bundle 1 = MAGISTRACY, REVENUE, ELECTION, RTI

## Posts that hold every function of their office (no allotment rows)

- CO: Business instruction (03-11-2026): the Circle Officer holds all functions of the circle office
- CDC: Nagaon order 13-03-2026: the CDC 'will manage all tasks related to the co-district'
- DC: DEMO: head of office; the Nagaon order allots branches 'subject to the overall supervision of the undersigned'
- DAO: DEMO: single-officer department office
- REG: DEMO: council office
- PRES: DEMO: council office

## Demo Sub Registrars (Link Officer for a lone Circle Officer)

- 31 circle offices with a CO each get a demo Sub Registrar (SR): AS-CR-285-01, AS-CR-285-02, AS-CR-285-03, AS-CR-285-04, AS-CR-285-05, AS-CR-285-06, AS-CR-285-07, AS-CR-285-08, AS-CR-297-01, AS-CR-297-03, AS-CR-297-06, AS-CR-298-01, AS-CR-298-02, AS-CR-298-03, AS-CR-298-04, AS-CR-298-05, AS-CR-298-06, AS-CR-298-07, AS-CR-302-01, AS-CR-302-02, AS-CR-302-03, AS-CR-302-04, CO_AZARA, CO_CHANDRAPUR, CO_DISPUR, CO_GUWAHATI, CO_KALIABOR, CO_NAGAON, CO_RAHA, CO_SAMAGURI, CO_SONAPUR. Business decision 03-11-2026: the Sub Registrar sits in the circle office; no Sub Registrar is named in any source, so each circle office with a CO gets a demo one.

## Cross-check against Sewa_Setu_PoC_Linked_Masters.xlsx

- ACS-4014 'Nimashri Dauka': earlier PoC had Assistant Commissioner at Office of the District Commissioner, Tinsukia; now seeded as CO at Sadiya.
- ACS-4028 'Bombee Kumari' (Assistant Commissioner, Office of the District Commissioner, Tinsukia) is not on the current roster.
- ACS-4035 'Madhurima Dihingia' (Assistant Commissioner, Office of the District Commissioner, Tinsukia) is not on the current roster.
- ACS-4042 'Pronami Gogoi' (Assistant Commissioner, Office of the District Commissioner, Tinsukia) is not on the current roster.
- ACS-4105 'Dwithun Wary' (Assistant Commissioner, Office of the District Commissioner, Dhubri) is not on the current roster.
- ACS-4112 'Anuran Haloi' (Assistant Commissioner, Office of the District Commissioner, Dhubri) is not on the current roster.

## Invalid mobile numbers

- 'Megha NidhiDahal' (List_of_DCs.xlsx DC!row12): '918734207' is not 10 digits
- 'Manoj Kr. Dutta' (List_of_DCs.xlsx COs!row58.1): '967822652' is not 10 digits
- 'Dharmaraj Kalita' (Officers_Workallotment_13_03_26.pdf Sl 17): '600209809' is not 10 digits

## Shared mobile numbers (distinct people)

- 8638375323: Kamal Jeet Sarma, Mridul Boro

## Officers with no year of joining (seniority falls back to name)

- R-000008 Apurba Kr. Das (cadre unknown)
- R-000025 Reetimoni Das (ALRS)
- R-000028 Amarjyoti Nath (ALRS)
- R-000030 Sajjad Hussain (ALRS)
- R-000033 Sontush kumar Nath (ALRS)
- R-000034 Shahnawaz Ikbal (ALRS)
- R-000036 Rituparna Bhadra (ALRS)
- R-000037 Sangeeta Sarmah (ALRS)
- R-000038 Bilaob Sarma Bordoloi (ALRS)
- R-000040 Bipul Deka (ALRS)
- R-000041 Jaideep Rajak (ALRS)
- R-000042 Rantu Borah (ALRS)
- R-000043 Bikramjit Bora (ALRS)
- R-000044 Upasane Deka (ALRS)
- R-000047 Rosy Lhinglenkim Singson (ALRS)
- R-000050 Manish Bharali (ALRS)
- R-000052 Navajyoti Saharia (ALRS)
- R-000054 Gyanjyoti Dutta (ALRS)

## Ignored data

- `List_of_DCs.xlsx` sheet `COs`: 52 rows carry a second, unlabelled name list in columns G–I. With no header to say what it means, it is ignored.
- Districts outside the PoC (all but Nalbari, Kamrup Metropolitan, Dhubri, Tinsukia, Nagaon) are ignored.
- Gradation-list postings outside PoC offices are used only to enrich officers already found (year, DOB, email).
- `PoC_master_data.xlsx` **Officer Directory** (4483 rows) is not imported: its header says 'Officer Name (Demo)', mobiles are sequential and names repeat across posts, so the people are synthetic. Using them would fill gaps silently.
- `PoC_master_data.xlsx` sheets that map services and posts to ARTPS authority roles (Sheet1, Post Master, DPS Tier Map, Change Log, HR Validation) are not imported: roles belong to the Rule Engine.
- `PoC_master_data.xlsx` uses a third district-code scheme (Dhubri DHB, Kamrup Metropolitan KMM, Nagaon NGN, Nalbari NLB, Tinsukia TSK); kept as `external_ref` on DC offices only. Office IDs keep the spec's numeric codes.

## Offices (provisional IDs)

| office_id | name | type | provisional | external_ref |
|---|---|---|---|---|
| ACMR-00ASM | Assam Council of Medical Registration (state office) | DEPT_STATE_OFFICE | True | PoC_master_data.xlsx dept ACM |
| ACMR_KMM | Office of the Additional Commissioner (Revenue), Kamrup Metropolitan | ACMR_OFFICE | False |  |
| ACMR_NGN | Office of the Additional Commissioner (Revenue), Nagaon | ACMR_OFFICE | False |  |
| AS-CR-285-01 | Office of the Circle Officer, Agomani | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master DHB-C04 AGOMANI |
| AS-CR-285-02 | Office of the Circle Officer, Athani | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master DHB-C01 ATHANI |
| AS-CR-285-03 | Office of the Circle Officer, Bilasipara | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master DHB-C02 BILASIPARA |
| AS-CR-285-04 | Office of the Circle Officer, Chapor | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master DHB-C03 CHAPOR |
| AS-CR-285-05 | Office of the Circle Officer, Dhubri | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master DHB-C05 DHUBRI |
| AS-CR-285-06 | Office of the Circle Officer, Gauripur | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master DHB-C06 GAURIPUR |
| AS-CR-285-07 | Office of the Circle Officer, Golakaganz | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master DHB-C07 GOLAKAGANZ |
| AS-CR-285-08 | Office of the Circle Officer, South Shalamara(Part) | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master DHB-C08 SOUTH SHALAMARA (PART) |
| AS-CR-297-01 | Office of the Circle Officer, Dhing | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NGN-C03 DHING |
| AS-CR-297-03 | Office of the Circle Officer, Kamapur | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NGN-C04 KAMAPUR |
| AS-CR-297-06 | Office of the Circle Officer, Rupahi | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NGN-C07 RUPAHI |
| AS-CR-297-08 | Office of the Circle Officer, Samaguri (K) | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NGN-C02 SAMAGURI (K) |
| AS-CR-298-01 | Office of the Circle Officer, Banekuchi | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NLB-C01 BANEKUCHI |
| AS-CR-298-02 | Office of the Circle Officer, Barbhag | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NLB-C02 BARBHAG |
| AS-CR-298-03 | Office of the Circle Officer, Barkhetri | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NLB-C03 BARKHETRI |
| AS-CR-298-04 | Office of the Circle Officer, Ghograpar | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NLB-C04 GHOGRAPAR |
| AS-CR-298-05 | Office of the Circle Officer, Nalabari | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NLB-C05 NALABARI |
| AS-CR-298-06 | Office of the Circle Officer, Paschim Nalbari | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NLB-C06 PASCHIM NALBARI |
| AS-CR-298-07 | Office of the Circle Officer, Tihu | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NLB-C07 TIHU |
| AS-CR-302-01 | Office of the Circle Officer, Doomdooma | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master TSK-C03 DOOMDOOMA |
| AS-CR-302-02 | Office of the Circle Officer, Margherita | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master TSK-C01 MARGHERITA |
| AS-CR-302-03 | Office of the Circle Officer, Sadia | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master TSK-C02 SADIA |
| AS-CR-302-04 | Office of the Circle Officer, Tinsukia | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master TSK-C04 TINSUKIA |
| AS-D-285 | Office of the District Commissioner, Dhubri | DC_OFFICE | False | PoC_master_data.xlsx Geo Master district DHB |
| AS-D-298 | Office of the District Commissioner, Nalbari | DC_OFFICE | False | PoC_master_data.xlsx Geo Master district NLB |
| AS-D-302 | Office of the District Commissioner, Tinsukia | DC_OFFICE | False | PoC_master_data.xlsx Geo Master district TSK |
| BVO_DIMORIA | Block Veterinary Office, Dimoria | BLOCK_VET_OFFICE | False |  |
| BVO_KALIABOR | Block Veterinary Office, Kaliabor | BLOCK_VET_OFFICE | False |  |
| BVO_PAKHIMORIA | Block Veterinary Office, Pakhimoria | BLOCK_VET_OFFICE | False |  |
| BVO_RAHA | Block Veterinary Office, Raha | BLOCK_VET_OFFICE | False |  |
| BVO_RANI | Block Veterinary Office, Rani | BLOCK_VET_OFFICE | False |  |
| CDO-20NEW | Co-District Office, New Ghy | SUBDIV_OFFICE | True |  |
| CO_AZARA | Azara Revenue Circle Office | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master KMM-C01 AZARA |
| CO_CHANDRAPUR | Chandrapur Revenue Circle Office | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master KMM-C04 SANDRAPUR |
| CO_DISPUR | Dispur Revenue Circle Office | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master KMM-C02 DISPUR |
| CO_GUWAHATI | Guwahati Revenue Circle Office | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master KMM-C03 GUWAHATI |
| CO_KALIABOR | Kaliabor Revenue Circle Office | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NGN-C01 KALIABAR |
| CO_NAGAON | Nagaon Revenue Circle Office | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NGN-C05 NAGAON |
| CO_RAHA | Raha Revenue Circle Office | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NGN-C06 RAHA |
| CO_SAMAGURI | Samaguri Revenue Circle Office | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master NGN-C08 SAMAGURI |
| CO_SONAPUR | Sonapur Revenue Circle Office | CIRCLE_OFFICE | False | PoC_master_data.xlsx Geo Master KMM-C05 SONAPUR |
| DAO_D-298 | District Agriculture Office, Nalbari | DEPT_DISTRICT_OFFICE | False |  |
| DAO_KMM | District Agriculture Office, Kamrup Metropolitan | DISTRICT_AGRICULTURE_OFFICE | False |  |
| DAO_NGN | District Agriculture Office, Nagaon | DISTRICT_AGRICULTURE_OFFICE | False |  |
| DC_KMM | Office of the District Commissioner, Kamrup Metropolitan | DC_OFFICE | False | PoC_master_data.xlsx Geo Master district KMM |
| DC_NGN | Office of the District Commissioner, Nagaon | DC_OFFICE | False | PoC_master_data.xlsx Geo Master district NGN |
| DVO_KMM | District Veterinary Office, Kamrup Metropolitan | DISTRICT_VET_OFFICE | False |  |
| DVO_NGN | District Veterinary Office, Nagaon | DISTRICT_VET_OFFICE | False |  |
| EE_KMM | District Employment Exchange, Kamrup Metropolitan | EMPLOYMENT_EXCHANGE | False |  |
| EE_NGN | District Employment Exchange, Nagaon | EMPLOYMENT_EXCHANGE | False |  |
| SDO_D-285-BILASI | Co-District Office, Bilasipara | SUBDIV_OFFICE | False |  |
| SDO_D-285-GOL | Co-District Office, Golakganj | SUBDIV_OFFICE | False |  |
| SDO_D-285-SDR | Sadar Sub-division Office, Dhubri Sadar | SUBDIV_OFFICE | False |  |
| SDO_D-298-SDR | Sadar Sub-division Office, Nalbari Sadar | SUBDIV_OFFICE | False |  |
| SDO_D-302-DIG | Co-District Office, Digboi | SUBDIV_OFFICE | False |  |
| SDO_D-302-DOO | Co-District Office, Doomdooma | SUBDIV_OFFICE | False |  |
| SDO_D-302-MAK | Co-District Office, Makum | SUBDIV_OFFICE | False |  |
| SDO_D-302-MAR | Co-District Office, Margherita | SUBDIV_OFFICE | False |  |
| SDO_D-302-SAD | Co-District Office, Sadiya | SUBDIV_OFFICE | False |  |
| SDO_D-302-SDR | Sadar Sub-division Office, Tinsukia Sadar | SUBDIV_OFFICE | False |  |
| SDO_KMM-DIM | Co-District Office, Dimoria | SUBDIV_OFFICE | False |  |
| SDO_KMM-DIS | Co-District Office, Dispur | SUBDIV_OFFICE | False |  |
| SDO_KMM-GUW | Sadar Sub-division Office, Guwahati Sadar | SUBDIV_OFFICE | False |  |
| SDO_KMM-JAL | Co-District Office, Jalukbari | SUBDIV_OFFICE | False |  |
| SDO_KMM-NEW | Co-District Office, New Guwahati | SUBDIV_OFFICE | False |  |
| SDO_KMM-SNP | Sub-district Office, Sonapur | SUBDIV_OFFICE | False |  |
| SDO_NGN-KLB | Sub-district Office, Kaliabor | SUBDIV_OFFICE | False |  |
| SDO_NGN-RAHA | Co-District Office, Raha | SUBDIV_OFFICE | False |  |
| SDO_NGN-SDR | Sadar Sub-division Office, Nagaon Sadar | SUBDIV_OFFICE | False |  |
| SR_KMM-GUW | Sub Registrar Office, Guwahati Sadar | SUB_REGISTRAR_OFFICE | False |  |
| SR_KMM-SNP | Sub Registrar Office, Sonapur | SUB_REGISTRAR_OFFICE | False |  |
| SR_NGN-KLB | Sub Registrar Office, Kaliabor | SUB_REGISTRAR_OFFICE | False |  |
| SR_NGN-SDR | Sub Registrar Office, Nagaon Sadar | SUB_REGISTRAR_OFFICE | False |  |

## Bound to MDM (seed.bind)

- 84 real officers carry MDM Employee IDs; 44 demo officers stay local (DEMO-NNNN).
- 128 postings and 201 function allotments re-keyed to MDM IDs and chairs.
- Local demo chairs (beyond MDM's sanctioned strength): ACMR-00ASM-PRESIDENT-D01, ACMR-00ASM-REGISTRAR-D01, AS-D-285-ADC-D01, AS-D-285-ADC-D02, AS-D-298-ADC-D01, AS-D-298-ADC-D02, AS-D-302-ADC-D01, AS-D-302-ADC-D02, DC_KMM-ADC-D01, DC_KMM-ADC-D02
- Offices kept locally (not in MDM): ACMR-00ASM Assam Council of Medical Registration (state office)
