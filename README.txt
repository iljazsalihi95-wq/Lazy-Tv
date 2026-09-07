LazyTV FIX
============
1. Në GitHub repo Lazy-Tv:
   - zëvendëso index.html me këtë index.html
   - te /data/ zëvendëso skedarin me këtë data/channels.json
2. Emri duhet të mbetet saktë: channels.json
3. JSON-i përmban 581 kanale dhe tokenat e tyre.
4. Shqipëri/Kosovë/Maqedoni numërohen nga fusha country.
5. Player-i nuk rri më në loading pafund:
   - provon MPEG-TS kur browseri e lejon;
   - në GitHub HTTPS + stream HTTP tregon qartë bllokimin dhe jep buton për VLC / hapje direkte.
