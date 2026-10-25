-- Az admin „▶ Ellenőrzés most” gombjának utolsó eredménye mérési esetenként (eval/quick_check.py).
ALTER TABLE eval_cases
    ADD COLUMN last_check    jsonb,
    ADD COLUMN last_check_at timestamptz;
