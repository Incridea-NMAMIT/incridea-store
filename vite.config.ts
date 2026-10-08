import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig(() => {
  const environment = process.env.PROD_ENV ?? 'VERCEL';
  if (!['VPS', 'VERCEL'].includes(environment)) throw new Error('PROD_ENV must be VPS or VERCEL');
  return {plugins:[react()],define:{'import.meta.env.PROD_ENV':JSON.stringify(environment)}};
});
