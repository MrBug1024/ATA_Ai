-- 权限网关 · role_code 英文化标准化迁移
-- 说明：
-- 1. 执行会修改 app_role_permission / app_user_role 中的角色码，属于数据库修改，必须经用户授权。
-- 2. role_code 只能保存英文稳定码；中文展示名保存到 app_role_permission.role_name。
-- 3. 本迁移保留权限语义不变，只替换角色编码。

ALTER TABLE public.app_role_permission
    ADD COLUMN IF NOT EXISTS role_name TEXT NOT NULL DEFAULT '';

COMMENT ON COLUMN public.app_role_permission.role_code IS
'英文稳定角色码，只允许小写字母、数字、下划线，且必须以字母开头；中文名称放 role_name。';
COMMENT ON COLUMN public.app_role_permission.role_name IS
'角色展示名，可为中文；不得用于权限判断。';

INSERT INTO public.app_role_permission (role_code, role_name, tier, modules, description) VALUES
  ('super_admin','全局超级管理员','management','["*"]','内部超级管理员；可跨公司，仅用于运维/初始化，必须审计'),
  ('company_admin','公司管理员','management','["*"]','私有化/多租户公司管理员；仅限本公司全权，不能跨公司'),
  ('project_manager','项目经理','management','["*"]','项目负责人，全模块+管理'),
  ('investment_specialist','投资专员','management','["report","drilldown","review","progress","deadline","graph"]','投资决策'),
  ('legal_specialist','法务专员','expert','["report","drilldown","review","corrections","deadline","graph"]','法务'),
  ('finance_specialist','财审专员','expert','["report","drilldown","review","progress","corrections","graph"]','财务审计'),
  ('due_diligence_specialist','尽调专员','expert','["report","drilldown","deadline","graph"]','尽职调查'),
  ('lawyer','律所律师','expert','["report","drilldown","review","corrections","deadline","graph"]','外部律师'),
  ('project_assistant','项目助理','field','["report","progress","deadline"]','项目助理'),
  ('legal_assistant','法辅专员','field','["report","drilldown","deadline"]','法务辅助')
ON CONFLICT (role_code) DO UPDATE SET
    role_name = EXCLUDED.role_name,
    tier = EXCLUDED.tier,
    modules = EXCLUDED.modules,
    description = EXCLUDED.description,
    updated_at = now();

UPDATE public.app_user_role
SET role_code = CASE role_code
    WHEN '__admin__' THEN 'super_admin'
    WHEN '公司管理员' THEN 'company_admin'
    WHEN '项目经理' THEN 'project_manager'
    WHEN '投资专员' THEN 'investment_specialist'
    WHEN '法务专员' THEN 'legal_specialist'
    WHEN '财审专员' THEN 'finance_specialist'
    WHEN '尽调专员' THEN 'due_diligence_specialist'
    WHEN '律所律师' THEN 'lawyer'
    WHEN '项目助理' THEN 'project_assistant'
    WHEN '法辅专员' THEN 'legal_assistant'
    ELSE role_code
END,
updated_at = now()
WHERE role_code IN (
    '__admin__',
    '公司管理员',
    '项目经理',
    '投资专员',
    '法务专员',
    '财审专员',
    '尽调专员',
    '律所律师',
    '项目助理',
    '法辅专员'
);

DELETE FROM public.app_role_permission
WHERE role_code IN (
    '__admin__',
    '公司管理员',
    '项目经理',
    '投资专员',
    '法务专员',
    '财审专员',
    '尽调专员',
    '律所律师',
    '项目助理',
    '法辅专员'
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_app_role_permission_role_code_ascii'
          AND conrelid = 'public.app_role_permission'::regclass
    ) THEN
        ALTER TABLE public.app_role_permission
            ADD CONSTRAINT ck_app_role_permission_role_code_ascii
            CHECK (role_code ~ '^[a-z][a-z0-9_]*$');
    END IF;
END $$;
