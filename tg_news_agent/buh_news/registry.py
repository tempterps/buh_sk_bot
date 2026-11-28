"""Seed registry. `enabled` means the adapter has been successfully verified on this VPS."""
SOURCES = [
 ('mf_sr','Ministerstvo financií SR','mfsr.sk',1,False,'https://www.mfsr.sk/sk/rss.html','https://www.mfsr.sk/sk/media/tlacove-spravy/?forceBrowserDetector=blind','rss',['tax','fiscal']),
 ('fs_press','Finančná správa – tlačové správy','financnasprava.sk',1,False,'https://www.financnasprava.sk/sk/rss/rss-tlacove-spravy','https://www.financnasprava.sk/sk/pre-media/tlacove-spravy','rss',['tax','dph','inspections']),
 ('fs_news','Finančná správa – novinky','financnasprava.sk',1,False,'https://www.financnasprava.sk/sk/rss/rss-novinky',None,'rss',['tax','dph']),
 ('social_insurance','Sociálna poisťovňa','socpoist.sk',1,False,'https://www.socpoist.sk/rss.xml','https://www.socpoist.sk/aktuality','rss',['contributions','employers']),
 ('nbs','Národná banka Slovenska','nbs.sk',1,False,'https://nbs.sk/feed/',None,'rss',['finance','payments']),
 ('podnikajte','Podnikajte','podnikajte.sk',2,False,'https://www.podnikajte.sk/rss','https://www.podnikajte.sk/dane-a-uctovnictvo','rss',['tax','business']),
 ('kros_tax','KROS – dane a odvody','kros.sk',2,False,'https://www.kros.sk/blog/kat/dane-a-odvody/feed/','https://www.kros.sk/blog/kat/dane-a-odvody/','rss',['tax']),
 ('kros_legislation','KROS – legislatíva','kros.sk',2,False,'https://www.kros.sk/blog/kat/legislativa/feed/',None,'rss',['legislation']),
 ('kros_payroll','KROS – mzdy','kros.sk',2,False,'https://www.kros.sk/blog/kat/mzdy-a-personalistika/feed/',None,'rss',['payroll']),
 ('podnikam','Podnikam','podnikam.sk',2,False,'https://podnikam.sk/feed/',None,'rss',['business']),
 ('skdp','SKDP','skdp.sk',1,False,'https://www.skdp.sk/','https://www.skdp.sk/','html',['tax']),
 ('humanet','Humanet','humanet.sk',2,False,'https://www.humanet.sk/blog/','https://www.humanet.sk/blog/','html',['payroll']),
 ('epi','EPI','epi.sk',2,False,'https://www.epi.sk/list/aktualne-informacie/',None,'html',['legislation']),
]

