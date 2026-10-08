import {z} from 'zod';
const release=z.object({tag:z.string(),versionCode:z.number().int().positive(),versionName:z.string().min(1),minimumSdk:z.number().int().positive(),size:z.number().int().positive(),sha256:z.string().regex(/^[a-f0-9]{64}$/),signingSha256:z.string().regex(/^[a-f0-9]{64}$/),sourceSha:z.string().regex(/^[a-f0-9]{40}$/),publishedAt:z.string().datetime(),downloadUrl:z.string().url().refine(url=>/^https:\/\/github\.com\/Incridea-NMAMIT\/incridea-store\/releases\/download\/[^/]+\/[^/]+\.apk$/.test(url)),changelog:z.string(),runId:z.string().regex(/^\d+$/)}).strict();
export const catalogSchema=z.object({schemaVersion:z.literal(1),updatedAt:z.string().datetime(),apps:z.array(z.object({packageId:z.enum(['in.incridea.dashboard','in.incridea.operations','in.incridea.pronite','in.incridea.deploy']),releases:z.array(release)}).strict()).max(4)}).strict().superRefine((c,ctx)=>{if(new Set(c.apps.map(a=>a.packageId)).size!==c.apps.length)ctx.addIssue({code:'custom',message:'Duplicate apps'});for(const a of c.apps)if(new Set(a.releases.map(r=>r.versionCode)).size!==a.releases.length)ctx.addIssue({code:'custom',message:'Duplicate version codes'});});
export type Catalog=z.infer<typeof catalogSchema>;
export type Release=z.infer<typeof release>;
export async function loadCatalog():Promise<Catalog>{
 const configured=(import.meta as unknown as {env:Record<string,string>}).env.VITE_CATALOG_URL;
 const url=configured??'https://raw.githubusercontent.com/Incridea-NMAMIT/incridea-store/catalog/catalog.json';
 if(!/^https:\/\/raw\.githubusercontent\.com\/Incridea-NMAMIT\/incridea-store\/catalog\/catalog\.json$/.test(url))throw Error('Invalid catalog origin');
 const response=await fetch(url,{cache:'no-cache',signal:AbortSignal.timeout(15000)});
 if(!response.ok)throw Error('The release catalog is temporarily unavailable.');
 return catalogSchema.parse(await response.json());
}
