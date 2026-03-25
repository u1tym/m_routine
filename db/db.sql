create schema plan;

-- 適用日
create table plan.routine_adapt_day (
    id            serial  primary key,
    explain       text    not null,        -- 説明
    what_number   integer not null,        -- 何番目(負数は末尾から)
    order_week    integer not null         -- 曜日指定(0=日曜日、6=土曜日、-1=指定なし)
        check (order_week between -1 and 6)
);

-- 調整
create table plan.routine_adjust_day (
    id            serial  primary key,
    explain       text    not null,                -- 説明
    avoid_holiday boolean not null default false,  -- 祝日除外
    avoid_sun     boolean not null default false,  -- 日曜除外
    avoid_mon     boolean not null default false,  -- 月曜除外
    avoid_tue     boolean not null default false,  -- 火曜除外
    avoid_wed     boolean not null default false,  -- 水曜除外
    avoid_thu     boolean not null default false,  -- 木曜除外
    avoid_fri     boolean not null default false,  -- 金曜除外
    avoid_sat     boolean not null default false,  -- 土曜除外
    alt_day       integer not null check (alt_day in (1, -1)) -- 代替日
);

-- ルーティン基本情報
create table plan.routine (
    id            serial  primary key,  -- 主キー
    title         text    not null,     -- 名称
    adapt_id      integer not null      -- 適用日ID
        references plan.routine_adapt_day(id) on delete restrict,
    adjust_id     integer               -- 調整日ID
        references plan.routine_adjust_day(id) on delete set null,
    is_deleted    boolean not null default false
);
alter table plan.routine add constraint uq_routine_title unique ( title );


-- 説明
-- plan.routine に、ルーティンの基本情報を格納する
--   id: 自動採番
--   title: 人が識別するための名称
--
-- plan.routine_adapt_day に、ルーティンを実行する日の情報を格納する
--   毎月 N日の場合には、what_number = N、order_week = -1
--   毎月末の場合には、what_number = -1、order_week = -1
--   第N X曜日の場合には、what_number = N、order_week = Xに応じた曜日の数字
--   order_weekには、曜日を限定して数えるか否か
--   what_numberには、何個目か（負数は末からカウント）
--
-- plan.routine_adjust_day に、除外する日と、その場合の代替日の情報を格納する
--   avoid_holiday は、祝日を除外するか否か。祝日は、public.holidaysに格納される日
--   avoid_sum～avoid_satは、日曜日～土曜日、それぞれを除外するか否か。
--   alt_dayは、1の場合は、未来日方向で、除外日から外れる最初の日を代替日にする
--             -1の場合は、過去方向で、除外日から外れる最初の日を代替日にする

alter table schedules add column routine_id integer;

alter table schedules
add constraint fk_schedules_routine
  foreign key (routine_id)
  references plan.routine(id)
  on delete set null;

-- ルーティンに基づいたスケジュールの場合に、IDを格納する

